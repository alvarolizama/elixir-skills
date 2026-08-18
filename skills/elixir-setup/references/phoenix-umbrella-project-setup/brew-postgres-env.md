# Homebrew PostgreSQL + mise + secrets cheat sheet

For local development on macOS with the phoenix-umbrella-project-setup skill.

## Check PostgreSQL

```bash
brew services info postgresql@17   # or just postgresql
brew services start postgresql@17
```

## Find your local role

Homebrew usually creates a superuser matching your macOS username, not `postgres`.

```bash
psql -l
# or
psql postgres -c "\du"
```

Use that username in `.env`:

```bash
DB_USER=alvaro
DB_PASSWORD=
DB_HOST=localhost
DB_NAME=money_bot_dev
```

## .mise.toml

```toml
[tools]
elixir = "1.20"
erlang = "27.0"

[env]
_.file = ".env"
```

No `source .env` needed. mise loads `.env` automatically when you `cd` into the project.

## .env.example

```bash
# Dev
DB_USER=postgres
DB_PASSWORD=
DB_HOST=localhost
DB_NAME=money_bot_dev

# Test (overrides DB_NAME)
# MIX_ENV=test sets DB_NAME=money_bot_test automatically in config/test.exs

# Prod
DATABASE_URL=postgres://user:***@host:5432/money_bot_prod
POOL_SIZE=10
SECRET_KEY_BASE_SITES=genera_un_secreto_real_con_mix_phx_gen_secret
SECRET_KEY_BASE_ADMIN=genera_otro_secreto_real_con_mix_phx_gen_secret
SITES_HOST=tu-dominio.com
ADMIN_HOST=admin.tu-dominio.com
SITES_PORT=4000
ADMIN_PORT=4001
```

## Generate real secrets

```bash
cp .env.example .env
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_SITES
mix phx.gen.secret | pbcopy   # SECRET_KEY_BASE_ADMIN
```

Paste each into `.env`.

## Test env loads test config

```bash
MIX_ENV=test mix run -e 'IO.puts(Application.get_env(:core, Core.Repo)[:database])'
```

Expected: `money_bot_test`

## Run everything

```bash
mix deps.get
mix ecto.setup
mix phx.server
```

## Unified `members` table (leads + active/inactive members)

Do not create a separate `leads` table. Model the entire lifecycle in `members`:

| status | password? | can log in? |
|--------|-----------|-------------|
| `lead` | no | no |
| `active` | yes | yes |
| `inactive` | yes | no |
| `banned` | yes | no |

Relevant changesets:

```elixir
def lead_changeset(member, attrs) do
  member
  |> cast(attrs, [:site_id, :email, :name, :metadata])
  |> validate_required([:site_id, :email])
  |> validate_format(:email, ~r/^[^\s]+@[^\s]+$/)
  |> unique_constraint(:email, name: :members_site_id_email_index)
  |> put_change(:status, "lead")
end

def registration_changeset(member, attrs) do
  member
  |> cast(attrs, [:site_id, :email, :password, :name, :metadata])
  |> validate_required([:site_id, :email, :password])
  |> validate_length(:password, min: 8)
  |> unique_constraint(:email, name: :members_site_id_email_index)
  |> put_password_hash()
  |> put_change(:status, "active")
end

def changeset(member, attrs) do
  member
  |> cast(attrs, [:status, :metadata])
  |> validate_inclusion(:status, ["lead", "active", "inactive", "banned"])
end

 defp put_password_hash(%Ecto.Changeset{valid?: true, changes: %{password: password}} = changeset) do
  put_change(changeset, :password_hash, Bcrypt.hash_pwd_salt(password))
end

 defp put_password_hash(changeset), do: changeset
```

Context helpers:

```elixir
def create_lead(attrs) do
  %Member{} |> Member.lead_changeset(attrs) |> Repo.insert()
end

def activate_member(%Member{status: "lead"} = lead, attrs) do
  lead
  |> Member.registration_changeset(attrs)
  |> Repo.update()
end

def activate_member(_, _), do: {:error, :not_a_lead}

def authenticate(site_id, email, password) do
  case get_active_member(site_id, email) do
    nil ->
      Bcrypt.no_user_verify()
      {:error, :invalid_credentials}
    member ->
      if Bcrypt.verify_pass(password, member.password_hash),
        do: {:ok, member},
        else: {:error, :invalid_credentials}
  end
end
```

Keep admin auth separate: use a global `users` table / `Core.Users` context for the admin dashboard, and `Core.Members` only for site-specific community auth.
