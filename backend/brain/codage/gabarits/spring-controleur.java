import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/commandes")
public class CommandeControleur {
    public record NouvelleCommande(@Positive long produitId, @Min(1) @Max(100) int quantite) {}

    private final CommandeService service;

    public CommandeControleur(CommandeService service) { this.service = service; }

    @PostMapping // @Valid : une requete invalide est refusee (400) en amont
    public ResponseEntity<Long> creer(@Valid @RequestBody NouvelleCommande commande) {
        return ResponseEntity.status(201).body(service.creer(commande));
    }
}
