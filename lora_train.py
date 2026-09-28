# -*- coding: utf-8 -*-
"""LoRA 微调训练脚本（骨架，供参考）。
运行前提：pip install transformers peft datasets torch accelerate
           + 一张 NVIDIA 显卡（或免费 Colab GPU）
现在先看懂流程，等你有 GPU / 数据攒够了再跑。

流程：加载开源模型 → 套 LoRA → 喂 JSONL 数据 → 训练 → 保存 adapter。
"""
# 1. 加载开源模型（例：Qwen/Qwen2.5-7B；显存小可换 1.5B/3B）
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
DATA_FILE = "微调数据.jsonl"

from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer
from datasets import load_dataset
from peft import LoraConfig, get_peft_model

# 2. 加载模型和分词器
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME, trust_remote_code=True, device_map="auto", torch_dtype="auto",
)

# 3. 配置 LoRA：只训 attention 的 q/v 投影，秩 r=16，这是"低秩适配"的核心
lora_config = LoraConfig(
    r=16,                       # 秩：越小越省，越大越能装细节（8~64 常见）
    lora_alpha=32,              # 缩放系数，通常 = 2*r
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()   # 看可训参数占比（通常 <1%）

# 4. 加载数据并 tokenize（messages 格式 → 输入 id）
dataset = load_dataset("json", data_files=DATA_FILE, split="train")

def tokenize_fn(ex):
    texts = []
    for msgs in ex["messages"]:
        texts.append(tokenizer.apply_chat_template(msgs, tokenize=False))
    return tokenizer(texts, truncation=True, max_length=512)

dataset = dataset.map(tokenize_fn, batched=True, remove_columns=dataset.column_names)

# 5. 训练
training_args = TrainingArguments(
    output_dir="./lora_output",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    num_train_epochs=3,
    learning_rate=2e-4,
    logging_steps=10,
    save_strategy="epoch",
)
trainer = Trainer(model=model, args=training_args, train_dataset=dataset)
trainer.train()

# 6. 保存 LoRA adapter（只存小矩阵，几 MB，不是整个模型）
model.save_pretrained("./lora_output/final")
print("训练完成，adapter 已保存到 ./lora_output/final")
