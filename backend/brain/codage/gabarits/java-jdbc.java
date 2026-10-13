import java.sql.*;
import java.util.Optional;

public final class ProduitDao {
    private final Connection connexion;

    public ProduitDao(Connection connexion) { this.connexion = connexion; }

    public Optional<String> nomDuProduit(long id) throws SQLException {
        String sql = "SELECT nom FROM produits WHERE id = ?";
        try (PreparedStatement req = connexion.prepareStatement(sql)) {
            req.setLong(1, id); // valeur liee, jamais concatenee
            try (ResultSet r = req.executeQuery()) {
                return r.next() ? Optional.of(r.getString("nom")) : Optional.empty();
            }
        }
    }
}
