using Academico.Data;
using Academico.Models;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace Academico.Controllers
{
    public class CasaApostaController : Controller
    {
        private readonly AcademicoContext _context;

        public CasaApostaController(AcademicoContext context)
        {
            _context = context;
        }

        public async Task<IActionResult> Index()
        {
            var casas = await _context.CasasApostas.OrderBy(c => c.Nome).ToListAsync();
            ViewData["SaldoTotal"] = casas.Sum(c => c.Saldo);
            return View(casas);
        }

        public async Task<IActionResult> Details(int? id)
        {
            if (id == null)
            {
                return NotFound();
            }

            var casaAposta = await _context.CasasApostas.SingleOrDefaultAsync(c => c.Id == id);
            if (casaAposta == null)
            {
                return NotFound();
            }

            return View(casaAposta);
        }

        public IActionResult Create()
        {
            return View();
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Create([Bind("Nome", "Saldo")] CasaAposta casaAposta)
        {
            try
            {
                if (ModelState.IsValid)
                {
                    _context.Add(casaAposta);
                    await _context.SaveChangesAsync();
                    return RedirectToAction(nameof(Index));
                }
            }
            catch (Exception)
            {
                ModelState.AddModelError("", "Não foi possível inserir os dados.");
            }

            return View(casaAposta);
        }

        public async Task<IActionResult> Edit(int? id)
        {
            if (id == null)
            {
                return NotFound();
            }

            var casaAposta = await _context.CasasApostas.FindAsync(id);
            if (casaAposta == null)
            {
                return NotFound();
            }

            return View(casaAposta);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Edit(int id, [Bind("Id", "Nome", "Saldo")] CasaAposta casaAposta)
        {
            if (id != casaAposta.Id)
            {
                return NotFound();
            }

            if (ModelState.IsValid)
            {
                try
                {
                    _context.Update(casaAposta);
                    await _context.SaveChangesAsync();
                }
                catch (DbUpdateConcurrencyException)
                {
                    if (!CasaApostaExists(casaAposta.Id))
                    {
                        return NotFound();
                    }
                    else
                    {
                        throw;
                    }
                }
                return RedirectToAction(nameof(Index));
            }

            return View(casaAposta);
        }

        public async Task<IActionResult> Delete(int? id)
        {
            if (id == null)
            {
                return NotFound();
            }

            var casaAposta = await _context.CasasApostas.SingleOrDefaultAsync(c => c.Id == id);
            if (casaAposta == null)
            {
                return NotFound();
            }

            return View(casaAposta);
        }

        [HttpPost, ActionName("Delete")]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> DeleteConfirmed(int id)
        {
            var casaAposta = await _context.CasasApostas.FindAsync(id);
            if (casaAposta != null)
            {
                _context.CasasApostas.Remove(casaAposta);
                await _context.SaveChangesAsync();
            }
            return RedirectToAction(nameof(Index));
        }

        public bool CasaApostaExists(int id)
        {
            return _context.CasasApostas.Any(e => e.Id == id);
        }
    }
}
