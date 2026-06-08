from pathlib import Path


def main(total: int = 5000):
    path = Path("config/tags.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for i in range(1, total + 1):
            fp.write(f"TAG_{i:06d}.VALUE\n")
    print(f"Generated {total} tags at {path}")


if __name__ == "__main__":
    main()
