"""Configuration Sentinelle.

Trois plans, trois budgets de latence (voir section 01 du plan d'architecture) :
  - plan bloquant    : < 100 ms, deterministe, aucun appel de modele
  - plan detection   : secondes, moteurs open source
  - plan analyse     : minutes, asynchrone, le cerveau
"""
import sys
from pathlib import Path

from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------ profil
# MAEL a deux vies :
#
#   LOCAL   l'outil que l'utilisateur installe chez lui. Pas de serveur, pas
#           de base, pas de file d'attente, pas d'API : le terminal et le
#           cerveau, rien d'autre. C'est ce qu'on publie le 1er octobre.
#   SERVEUR la plateforme d'origine (API, abonnements, collecte). Gelee
#           depuis le virage du 21/09, pas effacee.
#
# Les dependances du serveur (DRF, celery, redis, psycopg2, whitenoise...) ne
# sont PAS installees en local : tout ce qui les importe est donc conditionne
# ici, et non « au cas ou ». Un reglage absent ne doit jamais faire tomber le
# terminal avec une trace d'appel Python.
LOCAL = config("MAEL_LOCAL", default=False, cast=bool)

DEBUG = config("DEBUG", default=False, cast=bool)


def _cle_locale() -> str:
    """Cle de signature de l'installation locale.

    Django en exige une ; en local elle ne signe aucun cookie ni aucune
    session, mais la laisser a « dev-non-securise » serait un mauvais
    exemple dans un outil de securite. On en tire une au premier lancement
    et on la range chez l'utilisateur, lisible par lui seul."""
    import secrets
    import stat

    from brain.reglages import dossier

    chemin = dossier() / "cle"
    try:
        if chemin.exists():
            valeur = chemin.read_text(encoding="utf-8").strip()
            if valeur:
                return valeur
        chemin.parent.mkdir(parents=True, exist_ok=True)
        valeur = secrets.token_urlsafe(50)
        chemin.write_text(valeur + "\n", encoding="utf-8")
        try:                      # sans effet sous Windows, utile ailleurs
            chemin.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        return valeur
    except OSError:
        # Dossier en lecture seule : on tire une cle de session. L'outil
        # marche, elle ne survit pas au redemarrage -- sans consequence en
        # local.
        return secrets.token_urlsafe(50)


SECRET_KEY = (_cle_locale() if LOCAL
              else config("SECRET_KEY", default="dev-non-securise"))
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1").split(",")
if DEBUG:
    ALLOWED_HOSTS += ["testserver"]

# En local, Django ne sert qu'a charger la configuration et a trouver les
# commandes (« mael » = manage.py terminal). Tout le reste est du serveur.
APPS_LOCALES = [
    "django.contrib.contenttypes",
    "django.contrib.auth",          # exige par AUTH_USER_MODEL
    "core",                         # les commandes vivent la
]

INSTALLED_APPS = APPS_LOCALES if LOCAL else [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # tiers
    "rest_framework",
    "corsheaders",
    "django_filters",
    # socle
    "core",
    "billing",
    "assets",
    "intel",
    # modules vendus
    "modules.reputation",
    "modules.authguard",
]

MIDDLEWARE = [] if LOCAL else [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Aucune adresse servie en local (voir config/urls_locaux.py).
ROOT_URLCONF = "config.urls_locaux" if LOCAL else "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

if LOCAL:
    # Le terminal n'appelle jamais l'ORM (verifie le 21/09) : aucune base
    # n'est creee, aucune migration n'est necessaire. Cette entree n'existe
    # que parce que Django en exige une.
    from brain.reglages import dossier as _dossier_mael

    DATABASES = {"default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _dossier_mael() / "local.sqlite3",
    }}
else:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            config("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
            conn_max_age=600,
        )
    }

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if not LOCAL:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- DRF
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # les appels machine passent par la cle d'API...
        "billing.authentication.ApiKeyAuthentication",
        # ...les humains du tableau de bord par JWT
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "UNAUTHENTICATED_USER": None,
}

# ---------------------------------------------------------------- cache
REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "sentinelle",
        }
    }
else:
    # Dev sans Redis. En production, REDIS_URL est obligatoire : le cache
    # est ce qui tient le budget de 100 ms du plan bloquant.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "sentinelle-dev",
        }
    }

# ---------------------------------------------------------------- Celery
# File d'attente : serveur uniquement. En local, ni celery ni redis ne
# sont installes -- importer crontab ici ferait tomber le terminal.
if not LOCAL:
    from celery.schedules import crontab

    CELERY_BROKER_URL = REDIS_URL or "memory://"
    CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
    CELERY_TASK_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TIMEZONE = TIME_ZONE
    CELERY_TASK_TIME_LIMIT = 30 * 60
    # Un incident critique ne fait pas la queue derriere un rapport mensuel.
    # Planification. Definie ici et pas importee depuis intel.tasks : importer
    # un module qui touche aux modeles depuis settings.py leve AppRegistryNotReady.
    CELERY_BEAT_SCHEDULE = {
        "collecte-flux": {
            "task": "intel.tasks.collecter_tout",
            "schedule": crontab(minute=0, hour="*/4"),
        },
        "decroissance-quotidienne": {
            "task": "intel.tasks.decroissance_scores",
            "schedule": crontab(minute=30, hour=3),
        },
        "vidage-journal": {
            "task": "billing.tasks.vider_journal",
            "schedule": 10.0,
        },
        "reconciliation-quotas": {
            "task": "billing.tasks.reconcilier_quotas",
            "schedule": crontab(minute=5),
        },
        "geolocalisation-mensuelle": {
            "task": "intel.tasks.rafraichir_geo",
            "schedule": crontab(minute=0, hour=4, day_of_month=1),
        },
        "sante-des-flux": {
            "task": "intel.tasks.verifier_sante",
            "schedule": crontab(minute=15, hour="*/6"),
        },
    }

    CELERY_TASK_ROUTES = {
        "brain.tasks.analyser_incident": {"queue": "urgent"},
        "billing.tasks.vider_journal": {"queue": "urgent"},
        "reports.tasks.*": {"queue": "lent"},
        "intel.tasks.*": {"queue": "lent"},
    }

# ---------------------------------------------------------------- cerveau
def _budget_savoir_machine() -> int:
    """Budget de savoir adapte a la machine (brain/machine.py)."""
    try:
        from brain import machine
        return machine.budget_savoir_conseille()
    except Exception:            # noqa: BLE001
        return 700


def _contexte_machine() -> int:
    """Taille de contexte adaptee a la machine (brain/machine.py). Jamais
    une exception : si la mesure echoue, on garde l'ancien defaut."""
    try:
        from brain import machine
        return machine.contexte_conseille()
    except Exception:            # noqa: BLE001
        return 8192


def _moteur_par_defaut() -> str:
    """llamacpp si `mael installer` a pose un modele (MAEL-Coder), sinon
    Ollama, comme avant."""
    import json
    import os
    racine = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MAEL"
    try:
        pose = json.loads((racine / "installe.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return "ollama"
    return "llamacpp" if pose.get("modele") else "ollama"


BRAIN = {
    "BACKEND": config("BRAIN_BACKEND", default=_moteur_par_defaut()),
    "BASE_URL": config("BRAIN_BASE_URL", default="http://localhost:11434"),
    # Le moteur de MAEL (BRAIN_BACKEND=llamacpp, brain/backends/llamacpp.py) :
    # llama-server lance par MAEL lui-meme. Vides = trouves seuls dans
    # %LOCALAPPDATA%/MAEL/moteur et /modeles. 4 fils : mesure du 09/10 sur
    # le portable vise (i3 2 coeurs / 4 fils : 5,7 j/s en ecriture).
    "LLAMACPP": {
        "SERVEUR": config("BRAIN_LLAMA_SERVEUR", default=""),
        "MODELE": config("BRAIN_LLAMA_MODELE", default=""),
        "PORT": config("BRAIN_LLAMA_PORT", default=8089, cast=int),
        # 0 = d'apres la machine (8 192 sur 8 Go, plus sur une grande machine).
        "CONTEXTE": config("BRAIN_LLAMA_CONTEXTE", default=0, cast=int),
        "FILS": config("BRAIN_LLAMA_FILS", default=0, cast=int),
        "CACHE_RAM": config("BRAIN_LLAMA_CACHE_RAM", default=256, cast=int),
        # couches sur la carte graphique (-ngl) : 0 = tout sur le processeur ;
        # 999 = tout le modele sur la carte (Kaggle : 2 x T4)
        "GPU": config("BRAIN_LLAMA_GPU", default=0, cast=int),
    },
    # Le GRAND modele (BRAIN_BACKEND=vllm, brain/backends/vllm.py) :
    # installe sur la machine de MAEL (cartes graphiques) et servi par
    # `vllm serve`. Rien ne sort de la machine. Cle facultative
    # (vllm serve --api-key) : dans l'environnement, BRAIN_VLLM_CLE.
    "VLLM": {
        "URL": config("BRAIN_VLLM_URL", default="http://127.0.0.1:8000"),
        "MODELE": config("BRAIN_VLLM_MODELE", default=""),
        "CONTEXTE": config("BRAIN_VLLM_CONTEXTE", default=65536, cast=int),
        # taille d'apres la carte du modele (0 = traite comme grand)
        "MILLIARDS": config("BRAIN_VLLM_MILLIARDS", default=0, cast=float),
    },
    "MODELES": {
        # role logique -> modele concret. Le code n'appelle jamais un modele par son nom.
        "tri": config("BRAIN_MODEL_TRI", default="qwen3:8b"),
        "analyste": config("BRAIN_MODEL_ANALYSTE", default="qwen3:30b-a3b"),
        # Expert en terminal (audit/cybersecurite). Petit modele local :
        # tourne sans GPU, sur la machine de dev.
        "expert": config("BRAIN_MODEL_EXPERT", default="qwen2.5:3b"),
        # Atelier de code (brain/codage). Licence Apache 2.0 a cette taille
        # (la taille 3b de la meme famille ne l'est PAS : ne pas y descendre
        # sans verifier). Absent de la machine, brain.modeles choisit parmi
        # ce qui est installe, comme pour les autres roles.
        "codeur": config("BRAIN_MODEL_CODEUR", default="qwen2.5-coder:7b"),
    },
    # Les noms ci-dessus sont une INTENTION : brain/modeles.py les confronte a
    # ce qui est reellement installe chez l'utilisateur et choisit parmi ce qui
    # est la. Mis a vrai, ce drapeau interdit toute substitution : le modele
    # nomme tourne, ou MAEL s'arrete en le disant (banc de mesure, --modele).
    "MODELE_EXACT": config("BRAIN_MODELE_EXACT", default=False, cast=bool),
    # Combien de temps on laisse au modele pour repondre. 120 s convient a
    # un serveur avec carte graphique ; sur le portable de l'utilisateur, un
    # 3b met 130 s en profil court et 295 s en complet (mesure du 22/09).
    # Couper a 120 s, c'est rendre MAEL inutilisable chez exactement le
    # public qu'il vise. La connexion, elle, reste jugee en 5 s (ollama.py).
    "TIMEOUT": config("BRAIN_TIMEOUT", default=600 if LOCAL else 120,
                      cast=int),
    # Taille de contexte. 32k etouffe un petit modele sur une machine sans GPU
    # (RAM + lenteur). 8k suffit largement au terminal ; l'analyse serveur
    # peut remonter via l'env.
    "NUM_CTX": config("BRAIN_NUM_CTX", default=None) and
               config("BRAIN_NUM_CTX", cast=int) or
               (_contexte_machine() if LOCAL else 8192),
    # Longueur maximale d'une reponse, en jetons (examen du 09/10 : sans
    # borne, un plan a tourne en rond 3 800 jetons et 20 minutes).
    "NUM_PREDICT": config("BRAIN_NUM_PREDICT", default=2048, cast=int),
    # Combien de temps Ollama garde le modele en memoire entre deux
    # questions. Cinq minutes (son defaut) ne survivent pas a une pause :
    # la question suivante paie un rechargement complet depuis le disque.
    "GARDER_EN_MEMOIRE": config("BRAIN_KEEP_ALIVE",
                                default="30m" if LOCAL else "5m"),
    # Budget (en jetons estimes) du savoir de la bibliotheque injecte dans le
    # prompt. Il se paie en ATTENTE : le modele relit tout a chaque question
    # (26 jetons/s sur un portable sans carte graphique, mesure du 22/09).
    # D'ou un budget qui suit la machine en local ; le serveur garde
    # l'ancien comportement (700 en profil court, 1200 en complet).
    **({"BUDGET_SAVOIR": config("BRAIN_BUDGET_SAVOIR", cast=int)}
       if config("BRAIN_BUDGET_SAVOIR", default=None)
       else ({"BUDGET_SAVOIR": _budget_savoir_machine()} if LOCAL else {})),
    # En dessous de ce score, l'analyse part en revue humaine au lieu d'etre livree.
    "SEUIL_CONFIANCE": 0.65,
    # Profil du mode d'emploi : "complet" (production) ou "court" (dev sans GPU,
    # moins de jetons donc plus rapide). Meme comportement.
    "PROFIL": config("BRAIN_PROFIL", default="complet"),
    # Ce que la machine peut porter sert aussi a regler la taille du prompt :
    # voir brain/machine.py et le defaut du reglage « profil ».
}

# ---------------------------------------------------------------- outils
OUTILS = {
    "RUNTIME": config("TOOL_RUNTIME", default="docker"),
    # Plafond GLOBAL (1 h) ; chaque outil a son propre delai, plus court.
    # A 300 s, le plafond ecrasait Trivy (30 min) et ClamAV (1 h) : un scan
    # complet echouait toujours (19/09/2026).
    "TIMEOUT": config("TOOL_TIMEOUT", default=3600, cast=int),
}

# ---------------------------------------------------------------- securite
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS", default="http://localhost:5173"
).split(",")

# Pendant les TESTS (manage.py test, pytest), pas de redirection HTTPS :
# sans .env (CI, depot fraichement clone), DEBUG vaut False et chaque
# requete de test recevait une redirection 301 au lieu de sa reponse
# (52 tests en echec sur Linux vierge, 12/10/2026). En service, rien ne
# change.
EN_TEST = (len(sys.argv) > 1 and sys.argv[1] == "test") or \
    "pytest" in sys.modules

if not DEBUG and not EN_TEST:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "horodate": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "horodate"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # piste d'audit : tout appel d'outil et toute decision du cerveau
        "sentinelle.audit": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
