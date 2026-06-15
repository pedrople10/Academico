namespace Academico.Models
{
    public class Instituicao
    {
        public int Id { get; set; }
        public string Nome { get; set; } = string.Empty;
        public string Endereco { get; set; } = string.Empty;
        public virtual ICollection<Departamento>? Departamentos { get; set; }
    }
}
