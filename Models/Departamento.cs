using System.ComponentModel;

namespace Academico.Models
{
    public class Departamento
    {
        public int Id { get; set; }
        public string Nome { get; set; } = string.Empty;

        [DisplayName("Instituicao")]
        public int InstituicaoId { get; set; }
        public virtual Instituicao? Instituicao { get; set; }

        public virtual ICollection<Curso>? Cursos { get; set; }
    }
}
