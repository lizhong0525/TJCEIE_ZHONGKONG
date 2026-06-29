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

    使用 open_clip 分别编码图像与 8 个英文 prompt，按余弦相似度取 argmax，
    并将英文 prompt 映射回中文标签返回。
    """
    _load_model()

    # 文本特征只需计算一次，可在首次加载后缓存
    if not hasattr(do_classify, "_text_features"):
        text_tokens = _tokenizer(_english_prompts).to(_device)
        with torch.no_grad():
            text_features = _model.encode_text(text_tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)
        do_classify._text_features = text_features

    image_tensor = _transform(image).unsqueeze(0).to(_device)
    with torch.no_grad():
        image_features = _model.encode_image(image_tensor)
        image_features /= image_features.norm(dim=-1, keepdim=True)

    similarity = (image_features @ do_classify._text_features.T).squeeze(0)
    best_idx = int(similarity.argmax())
    label = _chinese_labels[best_idx]

    class_names = meta.get("class_names", [])
    if class_names and label not in class_names:
        # 平台会自行判断，这里仍返回 top-1，不记录日志
        pass

    return {"label": label}
