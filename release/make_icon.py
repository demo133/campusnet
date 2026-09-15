"""生成应用图标：release/app_icon.ico + campusnet/_icon_data.py。

设计：蓝色圆角方块 + 白色 Wi-Fi 弧线 + 圆点。
需要 Pillow（build_exe.py 会自动装）。重复运行无副作用。
"""
import base64
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SIZE = 256
CX = SIZE // 2
CY = 168          # Wi-Fi 圆点的圆心（也是两道弧的圆心）


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 蓝色圆角底
    d.rounded_rectangle([8, 8, SIZE - 8, SIZE - 8], radius=56,
                        fill=(37, 99, 235, 255))
    # 两道白色弧（开口朝上），线宽略不同制造层次
    for radius, width in ((74, 17), (46, 16)):
        d.arc([CX - radius, CY - radius, CX + radius, CY + radius],
              start=222, end=318, fill=(255, 255, 255, 255), width=width)
    # 圆点
    r = 15
    d.ellipse([CX - r, CY - r, CX + r, CY + r], fill=(255, 255, 255, 255))
    return img


def main() -> None:
    img = draw()

    # 1) Windows exe 图标：多尺寸 ICO
    ico_path = os.path.join(HERE, "app_icon.ico")
    img.save(ico_path, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                    (64, 64), (128, 128), (256, 256)])

    # 2) 窗口标题栏图标：32x32 PNG 的 base64，直接嵌进包里
    buf = img.resize((32, 32), Image.LANCZOS)
    import io
    bio = io.BytesIO()
    buf.save(bio, format="PNG")
    b64 = base64.b64encode(bio.getvalue()).decode("ascii")
    lines = [b64[i:i + 96] for i in range(0, len(b64), 96)]
    body = "\n".join('    "{}"'.format(x) for x in lines)

    out = os.path.join(ROOT, "campusnet", "_icon_data.py")
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('"""窗口图标（32x32 PNG 的 base64），由 release/make_icon.py 生成。"""\n')
        fh.write("\nICON_PNG_B64 = (\n{}\n)\n".format(body))
    print("已生成:", ico_path)
    print("已生成:", out)


if __name__ == "__main__":
    main()
