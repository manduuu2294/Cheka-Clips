import argparse
import base64
import gzip
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera el valor de YOUTUBE_COOKIES_GZIP_BASE64 para Railway."
    )
    parser.add_argument("cookies_file", help="Ruta al archivo cookies.txt en formato Netscape.")
    args = parser.parse_args()

    cookies_path = Path(args.cookies_file)
    raw = cookies_path.read_bytes()
    encoded = base64.b64encode(gzip.compress(raw)).decode("ascii")
    print(encoded)


if __name__ == "__main__":
    main()
