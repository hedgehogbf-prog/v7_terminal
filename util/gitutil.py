# util/gitutil.py
import subprocess
from datetime import datetime


def git_commit_logs(repo_dir: str, status_callback=None):
    """
    Простой git add/commit/push в указанном каталоге.
    status_callback(msg, color) – функция для отображения статуса (можно None).
    """
    def set_status(msg, color="white"):
        if status_callback:
            status_callback(msg, color)
        else:
            print(msg)

    try:
        set_status("Git: проверяю изменения…", "cyan")
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            set_status("Git: ошибка git status", "red")
            return
        if not res.stdout.strip():
            set_status("Git: нет изменений для коммита", "yellow")
            return

        set_status("Git: git add .", "cyan")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)

        msg = f"log update {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        set_status("Git: commit…", "cyan")
        subprocess.run(["git", "commit", "-m", msg], cwd=repo_dir, check=True)

        set_status("Git: push…", "cyan")
        subprocess.run(["git", "push"], cwd=repo_dir, check=True)

        set_status("Git: PUSH успешно", "green")
    except subprocess.CalledProcessError:
        set_status("Git: ошибка git команды", "red")
