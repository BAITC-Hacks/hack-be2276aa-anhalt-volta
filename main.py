"""Optional console interface: python main.py [--live]."""
import argparse
from agent import route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Use Gemini instead of offline demo')
    args = parser.parse_args()
    history = []
    print('Voice Router — exit для выхода')
    while True:
        try:
            text = input('Ты: ')
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip().lower() == 'exit':
            break
        try:
            result = route(text, history, 'live' if args.live else 'demo')
        except Exception:
            print('Не удалось обработать запрос. Проверьте ключ, модель и соединение.')
            continue
        print(result['reply'])
        history.extend([{'role': 'user', 'content': text}, {'role': 'assistant', 'content': result['reply']}])
        history = history[-12:]


if __name__ == '__main__':
    main()
