from typing import Any, Dict

import torch
from PIL import Image

# 8 个固定中文场景类别与对应的英文 open_clip 文本 prompt
_CLASS_PROMPTS = [
    ("办公室", "a photo of an office"),
    ("公园", "a photo of a park"),
    ("街道", "a photo of a street"),
    ("商场", "a photo of a shopping mall"),
    ("厨房", "a photo of a kitchen"),
    ("卧室", "a photo of a bedroom"),
    ("图书馆", "a photo of a library"),
    ("体育馆", "a photo of a gymnasium"),
]

_chinese_labels = [c for c, _ in _CLASS_PROMPTS]
_english_prompts = [p for _, p in _CLASS_PROMPTS]
_prompt_to_chinese = dict(_CLASS_PROMPTS)

# 模块级单例，首次调用时延迟加载
_model = None
_transform = None
_tokenizer = None
_device = None


def _load_model():
    """延迟初始化 open_clip 模型、预处理与 tokenizer。"""
    global _model, _transform, _tokenizer, _device
    if _model is not None:
        return

    import open_clip

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _model, _, _transform = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai"
    )
    _model = _model.to(_device).eval()
    _tokenizer = open_clip.get_tokenizer("ViT-B-32")


def do_classify(image: Image.Image, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    对输入图像进行零样本场景分类。
    使用多 prompt 投票提高准确率。
    """
    _load_model()
    
    class_names = meta.get("class_names", [])
    if not class_names:
        class_names = ["办公室", "公园", "街道", "商场", "厨房", "卧室", "图书馆", "体育馆"]
    
    # ---- 改动只有这里：从 1 条 prompt 变成 5 条 ----
    prompt_templates = [
        "a photo of a {}, typical scene",
        "an image of a {} environment",
        "a picture of a {}",
        "a view of a {}",
        "a scene with a {}",
    ]
    
    all_prompts = []
    for name in class_names:
        for template in prompt_templates:
            all_prompts.append(template.format(name))
    # --------------------------------------------
    
    text_tokens = _tokenizer(all_prompts).to(_device)
    with torch.no_grad():
        text_features = _model.encode_text(text_tokens)
        text_features /= text_features.norm(dim=-1, keepdim=True)
    
    image_tensor = _transform(image).unsqueeze(0).to(_device)
    with torch.no_grad():
        image_features = _model.encode_image(image_tensor)
        image_features /= image_features.norm(dim=-1, keepdim=True)
    
    similarity = (image_features @ text_features.T).squeeze(0)
    
    # ---- 改动只有这里：取平均分 ----
    num_classes = len(class_names)
    num_templates = len(prompt_templates)
    class_scores = []
    for i in range(num_classes):
        start = i * num_templates
        end = start + num_templates
        class_scores.append(similarity[start:end].mean())
    
    best_idx = int(torch.tensor(class_scores).argmax())
    # --------------------------------
    
    label = class_names[best_idx]
    return {"label": label}