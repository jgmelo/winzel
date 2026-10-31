"""Git repositories with work not sent anywhere: uncommitted changes, unpushed commits,
or a branch without a remote (the code has no copy outside this machine).

Only the direct subfolders of the projects folder that are repositories are checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..commands import CommandNotFound
from ..config import check_option, check_timeout
from ..context import Context
from ..models import CheckResult, Item, Metric, Status
from . import register
from .common import plural

CATEGORY = "git_repos"


@dataclass
class RepoState:
    name: str
    changes: int
    ahead: int
    has_upstream: bool

    @property
    def pending(self) -> bool:
        return self.changes > 0 or self.ahead > 0 or not self.has_upstream

    def describe(self) -> str:
        parts = []
        if self.changes:
            parts.append(plural(self.changes, "alteração", "alterações"))
        if not self.has_upstream:
            parts.append("sem remoto")
        elif self.ahead:
            parts.append(plural(self.ahead, "commit não enviado", "commits não enviados"))
        return f"{self.name} ({', '.join(parts)})"


def repo_state(ctx: Context, path: str, name: str, timeout_s: float) -> RepoState:
    def git(*args: str):
        return ctx.commands.run(
            ["git", "-C", path, *args], label=f"{CATEGORY}:{name}", timeout_s=timeout_s
        )

    status = git("status", "--porcelain")
    if status.returncode != 0:
        raise RuntimeError(f"git status falhou em {name}")
    changes = len([ln for ln in status.stdout.decode("utf-8", "replace").splitlines() if ln])
    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream.returncode != 0:
        return RepoState(name, changes, 0, has_upstream=False)
    ahead = git("rev-list", "--count", "@{u}..HEAD")
    count = int(ahead.stdout.decode().strip() or 0) if ahead.returncode == 0 else 0
    return RepoState(name, changes, count, has_upstream=True)


class GitReposCheck:
    id = CATEGORY
    label = "Repositórios git"
    area = "backup"
    requires_admin = False
    timeout_s = 60.0

    def run(self, ctx: Context) -> CheckResult:
        timeout_s = check_timeout(ctx.config, self.id, self.timeout_s)
        root = str(check_option(ctx.config, self.id, "projects_dir", "D:\\projetos")).rstrip("\\")
        try:
            names = ctx.fs.list_dirs(root)
        except FileNotFoundError:
            return CheckResult(self.id, Status.SKIPPED, f"indisponível: {root} não existe")
        repos = [n for n in names if ctx.fs.exists(f"{root}\\{n}\\.git")]
        try:
            states = [repo_state(ctx, f"{root}\\{n}", n, timeout_s) for n in repos]
        except CommandNotFound:
            return CheckResult(self.id, Status.SKIPPED, "indisponível: git não encontrado")
        pending = [s for s in states if s.pending]
        items = [
            Item(
                CATEGORY,
                s.name,
                None,
                {
                    "name": s.name,
                    "changes": s.changes,
                    "ahead": s.ahead,
                    "upstream": s.has_upstream,
                },
            )
            for s in states
        ]
        metrics = [Metric("git_repos_pending", len(pending), "repositórios")]
        total = plural(len(states), "repositório", "repositórios")
        if not pending:
            return CheckResult(self.id, Status.OK, f"{total}, tudo enviado", items, metrics)
        detail = "; ".join(s.describe() for s in pending)
        return CheckResult(
            self.id,
            Status.WARN,
            f"{len(pending)} de {total} com pendências: {detail}",
            items,
            metrics,
        )


register(GitReposCheck())
