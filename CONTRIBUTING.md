# Contributing Guidelines

## Branching

- Treat `main` as protected: **no direct commits or pushes.** All changes land via pull request.
- Branch from `main` using this naming scheme:

  ```
  <type>/<short-description>
  ```

  Examples: `feat/coach-athlete-roles`, `fix/refresh-token-expiry`, `chore/pin-bcrypt-version`

- Keep branches focused on one logical change. Split unrelated work into separate branches/PRs.
- **Keep PRs small: target under ~500 changed lines (excluding lockfiles/generated files).**
  If a feature is bigger than that, split it into a sequence of smaller PRs (e.g. "add User
  model + migration" → "add auth service" → "add auth API routes"). Large PRs get worse
  review and hide bugs.

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short summary>

<optional body>
```

**Types:**

| Type       | Use for                                                             |
|------------|----------------------------------------------------------------------|
| `feat`     | New feature                                                          |
| `fix`      | Bug fix                                                              |
| `docs`     | Documentation only                                                   |
| `style`    | Formatting, whitespace, no logic change                             |
| `refactor` | Code change that neither fixes a bug nor adds a feature              |
| `test`     | Adding or correcting tests                                           |
| `chore`    | Tooling, dependencies, build config, CI                              |
| `perf`     | Performance improvement                                              |

Examples:
```
feat(auth): add refresh token endpoint
fix(auth): reject access tokens used as refresh tokens
docs: add local setup instructions to README
chore: pin bcrypt to 4.0.1 for passlib compatibility
```

Keep the summary line under ~72 characters, imperative mood ("add", not "added"/"adds").

**Commit granularity:** commit each logical unit of work separately as you go - don't
squash an entire feature (model + service + API routes + tests + docs) into one commit.
Reviewers should be able to follow the change step by step, e.g.:

```
feat(auth): add User model and migration
feat(auth): add password hashing and JWT helpers
feat(auth): add signup/signin/refresh/me endpoints
test(auth): add unit and API tests for auth flow
docs: document backend setup and design decisions
```

This also makes the change reviewable step by step.


## Comments

**Keep comments concise.** Use short multiline comments when needed to explain safety constraints or non-obvious behavior

- Comment **why**, not what. Code should be somewhat self-explanatory
- Don't narrate history in a comment ("previously this did X"). That is what the commit
  message is for.

This is a review convention - no linter enforces comment length, so it is on reviewers
to push back.

## Pull requests

- Open a PR from your feature branch into `main`.
- PR title should follow the same `<type>: <summary>` convention as commits.
- PR description should cover:
  - What changed and why
  - How it was tested (e.g. "added pytest coverage for X", "manually verified via /docs")
  - Any follow-up work intentionally left out of scope
- At least one review approval required before merging (adjust in branch protection settings as the team grows).
- Delete the branch after merge.

### Size limit

Aim for **under 500 changed lines** (additions + deletions) per PR. Beyond roughly
that size, review quality drops and poor code can be waved through. Split larger
work into a stack of dependent PRs rather than shipping one large diff.

**Generated files are exempt.** 

### Merge strategy



**Merge commit for stacked PRs.** When PR B is based on PR A rather than `main`,
squashing A rewrites its commits, so B still carries the originals and git reports
duplicated changes and spurious conflicts - repeated down the whole stack. A merge
commit makes A's reviewed commits genuine ancestors of `main`, so the rest of the stack
stays clean. Merge a stack bottom-up, letting GitHub retarget each PR as its base
lands, and confirm CI is green at every step.



## Before opening a PR
- Don't commit `.env` or secrets. `.env.example` documents required variables.
