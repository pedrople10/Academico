using System.ComponentModel;

namespace Academico.Models
{
    public class Curso
    {
        public int Id { get; set; }
        public string Nome { get; set; } = string.Empty;
        public int CargaHoraria { get; set; }

        [DisplayName("Departamento")]
        public int DepartamentoId { get; set; }
        public virtual Departamento? Departamento { get; set; }
    }
}
