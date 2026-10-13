import java.security.SecureRandom;
import java.util.Base64;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

public final class Securite {
    private static final SecureRandom HASARD = new SecureRandom();
    private static final BCryptPasswordEncoder ENCODEUR = new BCryptPasswordEncoder(12);

    public static String jetonDeReinitialisation() {
        byte[] octets = new byte[32];
        HASARD.nextBytes(octets);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(octets);
    }

    public static String hacher(String motDePasse) { return ENCODEUR.encode(motDePasse); }

    public static boolean verifier(String motDePasse, String hache) {
        return ENCODEUR.matches(motDePasse, hache);
    }
}
