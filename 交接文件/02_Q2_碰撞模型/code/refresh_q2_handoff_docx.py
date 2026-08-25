from pathlib import Path

from docx import Document


DOCX = Path(__file__).resolve().parents[1] / "02_Q2_碰撞模型_论文手审阅.docx"

REPLACEMENTS = {
    "1. 本问到底要回答什么": "1. 本问目标",
    "2. 对公共模型和问题1的继承与本问新增": "2. 继承与新增",
    "3. 为什么这样设计碰撞模型": "3. 为什么这样建模",
    "4. 模型建立与完整求解过程": "4. 完整求解过程",
    "5. 问题2结果及其实际含义": "5. 结果及实际含义",
    "6. 模型检验、局限和下一问接口": "6. 检验、局限与下一问接口",
    "论文中应写成：": "统一论文表述：",
}


def main() -> None:
    document = Document(DOCX)
    changed = 0
    for paragraph in document.paragraphs:
        replacement = REPLACEMENTS.get(paragraph.text)
        if replacement is not None:
            paragraph.text = replacement
            changed += 1
    document.save(DOCX)
    print(f"updated={changed} path={DOCX}")


if __name__ == "__main__":
    main()
