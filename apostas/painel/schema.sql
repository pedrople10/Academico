-- Painel do apostador — schema Supabase
-- Rode isto uma vez no SQL Editor do seu projeto Supabase.

create table if not exists app_state (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb,
  updated_by text not null default 'painel', -- 'painel' (você, pelo navegador) ou 'claude' (sincronização)
  updated_at timestamptz not null default now()
);

alter table app_state enable row level security;

create policy "usuario le seus proprios dados"
  on app_state for select
  using (auth.uid() = user_id);

create policy "usuario insere seus proprios dados"
  on app_state for insert
  with check (auth.uid() = user_id);

create policy "usuario atualiza seus proprios dados"
  on app_state for update
  using (auth.uid() = user_id);

-- Habilita o Realtime (o site escuta mudanças nessa tabela e se atualiza sozinho)
alter publication supabase_realtime add table app_state;
