import nodes
import node_helpers
import torch
import comfy.model_management
import comfy.utils
import comfy.latent_formats
import comfy.clip_vision
import comfy.conds
import logging

class WanVaceToVideoAdvanced:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"model": ("MODEL",),
                            "positive": ("CONDITIONING", ),
                            "negative": ("CONDITIONING", ),
                            "vae": ("VAE", ),
                            "width": ("INT", {"default": 832, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
                            "height": ("INT", {"default": 480, "min": 16, "max": nodes.MAX_RESOLUTION, "step": 16}),
                            "length": ("INT", {"default": 81, "min": 1, "max": nodes.MAX_RESOLUTION, "step": 4}),
                            "batch_size": ("INT", {"default": 1, "min": 1, "max": 4096}),
                            "strength_inside": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1000.0, "step": 0.01}),
                            "strength_outside": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1000.0, "step": 0.01}),
                            "start_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                            "end_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                            "enable_console_logging": ("BOOLEAN", {"default": False}),
                },
                "optional": {"control_video": ("IMAGE", ),
                            "control_masks": ("MASK", ),
                            "reference_image": ("IMAGE", ),
                }}

    RETURN_TYPES = ("MODEL", "CONDITIONING", "CONDITIONING", "LATENT", "INT")
    RETURN_NAMES = ("model", "positive", "negative", "latent", "trim_latent")
    FUNCTION = "encode"

    CATEGORY = "conditioning/video_models"

    def encode(self, model, positive, negative, vae, width, height, length, batch_size, 
            strength_inside, strength_outside, start_percent, end_percent, 
            enable_console_logging=False,  # Add this parameter
            control_video=None, control_masks=None, reference_image=None):
        
        # Create a local debug function that uses the parameter
        def debug_log(message):
            """Conditional logging function"""
            if enable_console_logging:
                logging.info(message)
        
        params = {
            "strength_inside": strength_inside,
            "strength_outside": strength_outside,
            "start_percent": start_percent,
            "end_percent": end_percent
        }
        
        debug_log(f"[WanVaceDebug] Initial parameters - Strength Inside: {params['strength_inside']}, Strength Outside: {params['strength_outside']}, Start: {params['start_percent']}, End: {params['end_percent']}")
        
        # Clone the model
        cloned_model = model.clone() if hasattr(model, 'clone') else model
        
        # IMPORTANT: Reset any previous patches
        if hasattr(cloned_model.model, 'diffusion_model') and hasattr(cloned_model.model.diffusion_model, '_original_forward_orig'):
            cloned_model.model.diffusion_model.forward_orig = cloned_model.model.diffusion_model._original_forward_orig
            debug_log("[WanVaceDebug] Restored original forward_orig method")
            
        if hasattr(cloned_model.model, '_original_apply_model'):
            cloned_model.model.apply_model = cloned_model.model._original_apply_model
            debug_log("[WanVaceDebug] Restored original apply_model method")
        
        # Store current step info with thread-safe access
        import threading
        step_info_lock = threading.Lock()
        current_step_info = {
            "percent": 0.0, 
            "effective_strength": 0.0, 
            "sigma": None,
            "sample_sigmas": None,
            "initialized": False,
            "current_step_index": 0,
            "schedule_indices": 0
        }
        
        def update_step_info(sigma_value, model_options):
            """Update the current step information based on sigma value"""
            with step_info_lock:
                if sigma_value is None:
                    return
                    
                current_step_info["sigma"] = sigma_value
                
                # Get sample_sigmas from model_options
                sample_sigmas = None
                if isinstance(model_options, dict):
                    transformer_options = model_options.get("transformer_options", {})
                    if isinstance(transformer_options, dict):
                        sample_sigmas = transformer_options.get("sample_sigmas", None)
                
                if sample_sigmas is not None and isinstance(sample_sigmas, torch.Tensor) and sample_sigmas.numel() > 1:
                    current_step_info["sample_sigmas"] = sample_sigmas 
                    current_step_info["initialized"] = True
                    
                    # Calculate step index
                    total_steps_in_schedule = len(sample_sigmas)
                    schedule_indices = total_steps_in_schedule - 1
                    
                    if schedule_indices <= 0:
                        current_step_index = 0
                    else:
                        found_index = -1
                        # Try exact match first
                        sigma_tensor = torch.tensor(sigma_value)
                        matches = (torch.isclose(sigma_tensor, sample_sigmas, atol=1e-5, rtol=1e-5)).nonzero()
                        if len(matches) > 0:
                            found_index = matches[0].item()
                        else:
                            # Find between which sigmas we are
                            for i in range(schedule_indices):
                                s_curr = sample_sigmas[i].item()
                                s_next = sample_sigmas[i+1].item()
                                if s_curr >= sigma_value > s_next:
                                    found_index = i
                                    break
                            
                            # Handle edge cases
                            if found_index == -1:
                                if sigma_value >= sample_sigmas[0].item():
                                    found_index = 0
                                elif sigma_value <= sample_sigmas[-1].item():
                                    found_index = schedule_indices
                        
                        current_step_index = found_index if found_index != -1 else 0
                    
                    # Store step indices in current_step_info
                    current_step_info["current_step_index"] = current_step_index
                    current_step_info["schedule_indices"] = schedule_indices
                    
                    # Calculate percentage based on step index
                    current_step_info["percent"] = current_step_index / schedule_indices if schedule_indices > 0 else 0.0
                    
                    # Calculate effective strength using params dictionary with inside/outside logic
                    tolerance = 1e-5
                    is_inside_range = (current_step_info["percent"] >= params["start_percent"] - tolerance) and \
                                     (current_step_info["percent"] <= params["end_percent"] + tolerance)
                    
                    # Handle edge cases for exact 0.0 and 1.0
                    if params["start_percent"] == 0.0 and current_step_index == 0:
                        is_inside_range = True
                    if params["end_percent"] == 1.0 and current_step_index == schedule_indices:
                        is_inside_range = True
                    
                    # Use strength_inside when inside range, strength_outside when outside
                    current_step_info["effective_strength"] = params["strength_inside"] if is_inside_range else params["strength_outside"]

        # Store the original CFG function
        original_cfg_function = None
        if hasattr(model, 'model_config') and hasattr(model.model_config, 'sampler_config'):
            original_cfg_function = getattr(model.model_config.sampler_config, 'cfg_function', None)

        def strength_logging_wrapper(args):
            """Wrapper that tracks the current step and calculates percentage"""
            current_sigma_tensor = args.get("sigma", None)
            
            if current_sigma_tensor is not None and current_sigma_tensor.numel() > 0:
                update_step_info(current_sigma_tensor[0].item(), args.get("model_options", {}))
            
            # Call the original CFG function
            if original_cfg_function is not None:
                return original_cfg_function(args)
            else:
                # Default CFG calculation
                cond = args["cond"]
                uncond = args["uncond"]
                cond_scale = args["cond_scale"]
                
                if cond is None or uncond is None or cond_scale is None:
                    debug_log(f"[WanVaceDebug] Missing cond, uncond, or cond_scale in CFG wrapper.")
                    return args.get("uncond_denoised", uncond)
                
                return uncond + cond_scale * (cond - uncond)

        # Set the CFG function
        if hasattr(cloned_model, 'set_model_sampler_cfg_function'):
            cloned_model.set_model_sampler_cfg_function(strength_logging_wrapper)
            debug_log("[WanVaceDebug] Strength logging with step info enabled")

        # Patch the diffusion model's forward method to intercept vace_strength
        if hasattr(cloned_model.model, 'diffusion_model') and hasattr(cloned_model.model.diffusion_model, 'forward_orig'):
            # Store original before patching (only if not already stored)
            if not hasattr(cloned_model.model.diffusion_model, '_original_forward_orig'):
                cloned_model.model.diffusion_model._original_forward_orig = cloned_model.model.diffusion_model.forward_orig
            
            original_forward_orig = cloned_model.model.diffusion_model._original_forward_orig
            
            def patched_forward_orig(x, timestep, context, vace_context, vace_strength, **kwargs):
                """Patched forward_orig that uses the effective strength based on current step"""
                # First, try to update step info from kwargs if available
                if 'transformer_options' in kwargs:
                    sigma = kwargs['transformer_options'].get('sigmas', None)
                    if sigma is not None and sigma.numel() > 0:
                        update_step_info(sigma[0].item(), {'transformer_options': kwargs['transformer_options']})
                
                with step_info_lock:
                    effective_strength = current_step_info["effective_strength"]
                    current_percent = current_step_info["percent"]
                    current_step_index = current_step_info["current_step_index"]
                    schedule_indices = current_step_info["schedule_indices"]
                
                # Create a new tensor with the effective strength
                if isinstance(vace_strength, torch.Tensor):
                    vace_strength_modified = torch.full_like(vace_strength, effective_strength)
                else:
                    # Create a tensor with the batch size
                    vace_strength_modified = torch.full((x.shape[0],), effective_strength, 
                                                    device=x.device, 
                                                    dtype=x.dtype)
                
                # Determine if we're inside or outside the range for logging
                tolerance = 1e-5
                is_inside_range = (current_percent >= params["start_percent"] - tolerance) and \
                                 (current_percent <= params["end_percent"] + tolerance)
                if params["start_percent"] == 0.0 and current_step_index == 0:
                    is_inside_range = True
                if params["end_percent"] == 1.0 and current_step_index == schedule_indices:
                    is_inside_range = True
                
                range_status = "INSIDE" if is_inside_range else "OUTSIDE"
                
                debug_log(f"[WanVaceDebug] forward_orig: Step: {current_step_index}/{schedule_indices}, "
                            f"Percent: {current_percent:.3f}, "
                            f"Range: [{params['start_percent']:.3f}, {params['end_percent']:.3f}], "
                            f"Strength: {effective_strength:.4f}")
                
                # Call original with modified strength
                return original_forward_orig(x, timestep, context, vace_context, vace_strength_modified, **kwargs)
            
            # Replace the method
            cloned_model.model.diffusion_model.forward_orig = patched_forward_orig
            debug_log("[WanVaceDebug] Patched diffusion_model.forward_orig method")

        # Also patch the model's apply_model method to catch sigma updates earlier
        if hasattr(cloned_model.model, 'apply_model'):
            # Store original before patching (only if not already stored)
            if not hasattr(cloned_model.model, '_original_apply_model'):
                cloned_model.model._original_apply_model = cloned_model.model.apply_model
            
            original_apply_model = cloned_model.model._original_apply_model
            
            def patched_apply_model(x, t, c_concat=None, c_crossattn=None, control=None, transformer_options={}, **kwargs):
                # Update step info before calling the model
                if 'sigmas' in transformer_options:
                    sigma = transformer_options['sigmas']
                    if sigma is not None and sigma.numel() > 0:
                        update_step_info(sigma[0].item(), {'transformer_options': transformer_options})
                
                return original_apply_model(x, t, c_concat=c_concat, c_crossattn=c_crossattn, 
                                        control=control, transformer_options=transformer_options, **kwargs)
            
            cloned_model.model.apply_model = patched_apply_model
            debug_log("[WanVaceDebug] Patched model.apply_model method")

        # --- Original WanVaceToVideo logic ---
        latent_length = ((length - 1) // 4) + 1
        
        if control_video is not None:
            control_video = comfy.utils.common_upscale(control_video[:length].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            if control_video.shape[0] < length:
                control_video = torch.nn.functional.pad(control_video, (0, 0, 0, 0, 0, 0, 0, length - control_video.shape[0]), value=0.5)
        else:
            control_video = torch.ones((length, height, width, 3), device=comfy.model_management.intermediate_device()) * 0.5

        reference_image_latent = None
        if reference_image is not None:
            reference_image = comfy.utils.common_upscale(reference_image[:1].movedim(-1, 1), width, height, "bilinear", "center").movedim(1, -1)
            reference_image_latent = vae.encode(reference_image[:, :, :, :3])
            reference_image_latent = torch.cat([reference_image_latent, comfy.latent_formats.Wan21().process_out(torch.zeros_like(reference_image_latent))], dim=1)

        if control_masks is None:
            mask = torch.ones((length, height, width, 1), device=comfy.model_management.intermediate_device())
        else:
            mask = control_masks
            if mask.ndim == 3:
                mask = mask.unsqueeze(1)
            mask = comfy.utils.common_upscale(mask[:length], width, height, "bilinear", "center").movedim(1, -1)
            if mask.shape[0] < length:
                mask = torch.nn.functional.pad(mask, (0, 0, 0, 0, 0, 0, 0, length - mask.shape[0]), value=1.0)

        control_video = control_video - 0.5
        inactive = (control_video * (1 - mask)) + 0.5
        reactive = (control_video * mask) + 0.5

        inactive = vae.encode(inactive[:, :, :, :3])
        reactive = vae.encode(reactive[:, :, :, :3])
        control_video_latent = torch.cat((inactive, reactive), dim=1)
        
        if reference_image_latent is not None:
            control_video_latent = torch.cat((reference_image_latent, control_video_latent), dim=2)

        vae_stride = 8
        height_mask = height // vae_stride
        width_mask = width // vae_stride
        mask = mask.view(length, height_mask, vae_stride, width_mask, vae_stride)
        mask = mask.permute(2, 4, 0, 1, 3)
        mask = mask.reshape(vae_stride * vae_stride, length, height_mask, width_mask)
        mask = torch.nn.functional.interpolate(mask.unsqueeze(0), size=(latent_length, height_mask, width_mask), mode='nearest-exact').squeeze(0)

        trim_latent = 0
        if reference_image_latent is not None:
            mask_pad = torch.zeros_like(mask[:, :reference_image_latent.shape[2], :, :])
            mask = torch.cat((mask_pad, mask), dim=1)
            latent_length += reference_image_latent.shape[2]
            trim_latent = reference_image_latent.shape[2]

        mask = mask.unsqueeze(0)

        # Use strength_inside for the conditioning (this is the baseline strength value)
        positive = node_helpers.conditioning_set_values(positive, {"vace_frames": [control_video_latent], "vace_mask": [mask], "vace_strength": [strength_inside]}, append=True)
        negative = node_helpers.conditioning_set_values(negative, {"vace_frames": [control_video_latent], "vace_mask": [mask], "vace_strength": [strength_inside]}, append=True)

        latent = torch.zeros([batch_size, control_video_latent.shape[1], latent_length, height // 8, width // 8], device=comfy.model_management.intermediate_device())
        out_latent = {"samples": latent}
        
        return (cloned_model, positive, negative, out_latent, trim_latent)

NODE_CLASS_MAPPINGS = {
    "WanVaceToVideoAdvanced": WanVaceToVideoAdvanced,
}
