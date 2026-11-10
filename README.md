# Portfólio — Pedro

Projetos de desenvolvimento web que construí durante a faculdade. Cada seção explica o problema, o que o projeto faz e as
tecnologias usadas.

| Projeto | Stack principal | Demo |
|---|---|---|
| [Sistema Acadêmico (ASP.NET Core MVC)](#sistema-acadêmico-aspnet-core-mvc) | C#, .NET 8, Entity Framework Core, SQL Server | rodar localmente |

---

## Sistema Acadêmico (ASP.NET Core MVC)

📂 raiz do repositório ([`Controllers/`](Controllers/), [`Models/`](Models/), [`Views/`](Views/))

Sistema web de cadastro acadêmico feito na disciplina de desenvolvimento
web, seguindo o padrão MVC.

**Funcionalidades**

- CRUD completo (listar, detalhar, criar, editar e excluir) de
  **Instituições**, **Departamentos**, **Cursos** e **Alunos**.
- Relacionamentos entre entidades: uma instituição tem departamentos, e
  cada departamento tem cursos.
- Banco populado automaticamente com dados de exemplo na primeira execução.

**Tecnologias**

- C# com **ASP.NET Core MVC** (.NET 8) e views Razor
- **Entity Framework Core 8** com migrations
- **SQL Server LocalDB**
- Bootstrap e validação no cliente com jQuery Validation

**Como rodar**

```bash
dotnet restore
dotnet ef database update
dotnet run
```

Requer o .NET 8 SDK e o SQL Server LocalDB (instalado com o Visual Studio).
A string de conexão fica em `appsettings.json`.

---

## Contato

GitHub: [@pedrople10](https://github.com/pedrople10)
