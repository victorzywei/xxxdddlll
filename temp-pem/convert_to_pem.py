import textwrap
import sys
import os

def convert_to_pem(key_type: str):
    key_type = key_type.lower()
    if key_type not in ["private", "public"]:
        print("❌ 参数错误：请输入 'private' 或 'public'")
        return

    input_file = f"{key_type}.txt"
    output_file = f"{key_type}.pem"

    if not os.path.exists(input_file):
        print(f"❌ 未找到输入文件：{input_file}")
        print("请在当前目录放置一个包含 Base64 密钥内容的文件，例如：private.txt 或 public.txt")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        base64_str = f.read().strip().replace("\n", "").replace("\r", "")

    if key_type == "private":
        header = "-----BEGIN PRIVATE KEY-----"
        footer = "-----END PRIVATE KEY-----"
    else:
        header = "-----BEGIN PUBLIC KEY-----"
        footer = "-----END PUBLIC KEY-----"

    pem = f"{header}\n" + "\n".join(textwrap.wrap(base64_str, 64)) + f"\n{footer}\n"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pem)

    print(f"✅ 已生成 {output_file}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python convert_to_pem.py [private|public]")
        sys.exit(1)

    convert_to_pem(sys.argv[1])
