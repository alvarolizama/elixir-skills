---
name: phoenix-password-auth-bootstrap
description: "Add bcrypt password authentication to an existing Phoenix app that previously used only OAuth or env-var auth."
---

# Password Auth Bootstrapping Pattern

When an existing Phoenix app (OAuth-only or env-var-only) needs password-based
login with per-user records, this is the standard integration pattern.

## User Schema Changes

Add `password_hash` (persisted) and `password` (virtual) fields:

```elixir
schema "users" do
  # ... existing fields ...
  field :password_hash, :string
  field :password, :string, virtual: true
end
```

Separate changesets for different paths:

```elixir
# Admin-created / OAuth users (no password)
def changeset(user, attrs) do
  user
  |> cast(attrs, [:email, :name, :google_id, :avatar_url, :is_admin, :api_token])
  |> validate_required([:email])
  |> unique_constraint(:email)
end

# Self-registration or seed-created users (with password)
def registration_changeset(user, attrs) do
  user
  |> cast(attrs, [:email, :name, :password])
  |> validate_required([:email, :password])
  |> validate_format(:email, ~r/^[^\s]+@[^\s]+$/)
  |> validate_length(:password, min: 8)
  |> unique_constraint(:email)
  |> put_password_hash()
end

defp put_password_hash(%Ecto.Changeset{valid?: true, changes: %{password: pass}} = cs) do
  put_change(cs, :password_hash, Bcrypt.hash_pwd_salt(pass))
end
defp put_password_hash(cs), do: cs
```

## Accounts Context Functions

```elixir
def create_user_with_password(%{email: _, password: _} = attrs) do
  %User{}
  |> User.registration_changeset(attrs)
  |> Ecto.Changeset.put_change(:api_token, User.generate_api_token())
  |> Repo.insert()
end

def authenticate_user(email, password) do
  case get_user_by_email(email) do
    %User{password_hash: hash} when is_binary(hash) ->
      if Bcrypt.verify_pass(password, hash),
        do: {:ok, get_user_by_email(email)},
        else: {:error, :unauthorized}

    _ ->
      # Fallback: legacy env-var credentials for backward compat
      if LegacyAuth.valid_credentials?(email, password),
        do: {:ok, get_user_by_email(email)},
        else: {:error, :unauthorized}
  end
end
```

**Key:** The fallback to legacy auth lets existing deployments keep working
while new users get proper password hashing.

## Seed + Release Pattern (MyApp-style)

Env vars: `DRAN_ADMIN_EMAIL` + `DRAN_ADMIN_PASSWORD` (or equivalent).

**seeds.exs** (idempotent, runs in dev + prod):

```elixir
admin_email = System.get_env("DRAN_ADMIN_EMAIL")
admin_password = System.get_env("DRAN_ADMIN_PASSWORD")

if admin_email && admin_password do
  case Accounts.get_user_by_email(admin_email) do
    nil ->
      {:ok, user} = Accounts.create_user_with_password(%{
        email: admin_email, password: admin_password, name: "Admin"
      })
      Accounts.update_user(user, %{is_admin: true})
    %User{} = user ->
      unless user.is_admin, do: Accounts.update_user(user, %{is_admin: true})
  end
end
```

**Release.setup/0** — call `seed_admin()` after `migrate()`, before
`seed_context()`. The `seed_admin` function wraps the same logic inside
`Ecto.Migrator.with_repo` for release-safe execution (no Mix, no app started).

## Dependencies

```elixir
{:bcrypt_elixir, "~> 3.0"}  # or {:argon2_elixir, "~> 4.0"}
```

bcrypt_elixir compiles a NIF on first use — ensure build tools (cc, make)
are available in the build environment (Docker, CI).

## Migration

```elixir
def change do
  alter table(:users) do
    add :password_hash, :string
  end
end
```

Nullable by design — existing users (OAuth, env-var) have no hash. The
`password_hash` field only gets populated for password-based users.

## Pitfalls

- **`write_file` escapes quotes in .ex files.** The `write_file` tool
  sometimes produces double-escaped strings in Elixir files (e.g. `\"login\"`
  instead of `"login"`), causing `SyntaxError: unexpected token: "\"`.
  Use `patch` for Elixir file edits, or verify with `mix compile` after
  `write_file`.
- **Two changesets avoid password validation on OAuth paths.** If you add
  `validate_required([:password])` to the main `changeset/2`, Google OAuth
  users and admin-created users break. Keep them separate.
- **`Bcrypt.no_user_verify/0`** — call this in a plug or scheduler to prevent
  timing attacks that enumerate valid emails via hash computation time.
