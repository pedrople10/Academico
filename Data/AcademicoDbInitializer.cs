using Academico.Models;

namespace Academico.Data
{
    public class AcademicoDbInitializer
    {
        public static void Initialize(AcademicoContext context)
        {
            context.Database.EnsureCreated();

            if (context.Alunos.Any())
            {
                return;
            }

            var alunos = new Aluno[]
            {
                new Aluno
                {
                    Nome = "AlunoTeste",
                    Email = "alunoTeste@mail.com",
                    Telefone = "999999999",
                    Endereco = "Rua Teste",
                    Complemento = "Casa",
                    Bairro = "Bairro Teste",
                    Municipio = "Municipio Teste",
                    Uf = "UF",
                    Cep = "99999999"
                }
            };

            foreach (Aluno aluno in alunos)
            {
                context.Alunos.Add(aluno);
                context.SaveChanges();
            }
        }
    }
}
