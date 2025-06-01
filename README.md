# ComfyUi-WanVaceToVideoAdvanced

## 1) Intro
WanVaceToVideoAdvanced makes the Strength effect dynamic through time, this node:
- Adds additional “start_percent” and “end_percent” parameters to the WanVaceToVideo node
- Change "Strength" to "Strength_inside" and "Strength_outside"

Here's how the strength now behaves with these new settings
<img src="https://github.com/user-attachments/assets/f0f20bc7-493e-4432-8bce-0bb3751ec3ff" width="600" />

## 2) Use case
- Going for a high strength (e.g. strength = 1) provides a strong character's likelihood, but it makes the video too rigid and it doesn't follow the prompts anymore.
This is why having a dynamic strength can strike a balance between prompt understanding and character's likelihood

## 3) Install
Navigate to the **ComfyUI/custom_nodes** folder and run the following command in your terminal:

```git clone https://github.com/BigStationW/ComfyUi-RescaleCFGAdvanced```

## 4) Usage
- Use this [workflow](https://github.com/comfyanonymous/ComfyUI_examples/blob/master/wan/vace_reference_to_video.json)
- Replace WanVaceToVideo by WanVaceToVideoAdvanced

<img src="https://github.com/user-attachments/assets/0a1ea498-33f7-46ff-b435-22a1a2959c15" width="400" />

