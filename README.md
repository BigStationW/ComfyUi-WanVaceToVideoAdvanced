# ComfyUi-WanVaceToVideoAdvanced

## 1) Intro
WanVaceToVideoAdvanced makes the Strength effect dynamic through time, this node:
- Adds additional “start_percent” and “end_percent” parameters
- Change "Strength" into "Strength_inside" and "Strength_outside"

Here's how the strength now behaves with these new settings
<img src="https://github.com/user-attachments/assets/f0f20bc7-493e-4432-8bce-0bb3751ec3ff" width="600" />

## 2) Use case
- Using a high strength setting (e.g., strength = 1) helps preserve the character's appearance from the reference image, but it often makes the video too rigid and less responsive to the prompt.
  
That's why using a dynamic strength strikes a balance between having a good prompt understanding and maintaining the character's likeness.
![ezgif-24e5ff49fbb270](https://github.com/user-attachments/assets/4d305c12-df33-40c9-b0fc-58c425737ec9)

## 3) Install
Navigate to the **ComfyUI/custom_nodes** folder and run the following command in your terminal:

```git clone https://github.com/BigStationW/ComfyUi-RescaleCFGAdvanced```

## 4) Usage
- Use this [official workflow](https://github.com/comfyanonymous/ComfyUI_examples/blob/master/wan/vace_reference_to_video.json)
- Replace WanVaceToVideo by WanVaceToVideoAdvanced

<img src="https://github.com/user-attachments/assets/cf4dc31a-e56d-4b43-abf6-8ecfc2f2fc30" width="400" />

