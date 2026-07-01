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
    
    # 从平台请求中读取合法类别列表（这是关键！）
    class_names = meta.get("class_names", [])
    
    # 兜底：如果平台没下发（理论上不会），用默认8类
    if not class_names:
        class_names = ["办公室", "公园", "街道", "商场", "厨房", "卧室", "图书馆", "体育馆"]
    
    # 动态生成英文提示，不管类别是中文还是英文
    prompts = [f"a photo of a {name}" for name in class_names]
    
    # 动态生成文本特征（因为每次类别可能不同）
    text_tokens = _tokenizer(prompts).to(_device)
    with torch.no_grad():
        text_features = _model.encode_text(text_tokens)
        text_features /= text_features.norm(dim=-1, keepdim=True)
    
    # 计算图像特征
    image_tensor = _transform(image).unsqueeze(0).to(_device)
    with torch.no_grad():
        image_features = _model.encode_image(image_tensor)
        image_features /= image_features.norm(dim=-1, keepdim=True)
    
    # 计算相似度，取最高分
    similarity = (image_features @ text_features.T).squeeze(0)
    best_idx = int(similarity.argmax())
    label = class_names[best_idx]  # 直接用平台下发的类别名
    
    return {"label": label}
