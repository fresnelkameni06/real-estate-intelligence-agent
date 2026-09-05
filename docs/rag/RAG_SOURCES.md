# RAG Sources â€” Phase 6.1

Registre versionnÃ© des sources documentaires officielles pour le futur
sous-systÃ¨me RAG. **Cette phase ne fait que l'acquisition** : pas d'extraction,
pas de chunking, pas d'embeddings, pas de LLM.

## But de ce corpus

RÃ©pondre plus tard Ã  des questions **documentaires** (rÃ©glementation, mÃ©thodologie)
avec des rÃ©ponses **citÃ©es** et datÃ©es :
- Que signifie une Ã©tiquette DPE ?
- Quelles contraintes pour un logement classÃ© F ou G ?
- Quand un audit Ã©nergÃ©tique est-il requis ?
- Quelles sont les limites mÃ©thodologiques des donnÃ©es DVF / DPE ?

## FrontiÃ¨re entre analytique structurÃ©e et RAG

Les questions **numÃ©riques** (prix mÃ©dian/mÂ², volumes, tendances, classements,
distributions DPE) restent traitÃ©es par PostgreSQL et le moteur analytique
dÃ©terministe â€” **jamais** par le RAG ni approximÃ©es par un LLM. Le RAG ne sert
qu'aux questions **documentaires** (textes officiels).

## Sources sÃ©lectionnÃ©es

| source_id | Ã‰diteur | Sujet | Format | AutoritÃ© | Lien officiel |
|---|---|---|---|---|---|
| `comprendre_mon_dpe` | Min. Transition Ã©cologique | Grille de lecture du DPE (3CL, Aâ€“G) | PDF | official_guidance | [page DPE](https://www.ecologie.gouv.fr/politiques-publiques/diagnostic-performance-energetique-dpe) |
| `dpe_page_ministere` | Min. Transition Ã©cologique | DÃ©finition, validitÃ©, obligations DPE | HTML | official_guidance | [page DPE](https://www.ecologie.gouv.fr/politiques-publiques/diagnostic-performance-energetique-dpe) |
| `decence_gel_loyers_passoires` | Min. Transition Ã©cologique | DÃ©cence Ã©nergÃ©tique, gel des loyers F/G | HTML | official_guidance | [page dÃ©cence](https://www.ecologie.gouv.fr/politiques-publiques/location-gel-loyers-passoires-energetiques) |
| `audit_energetique_reglementaire` | Min. Transition Ã©cologique | Audit Ã©nergÃ©tique requis (vente passoires) | HTML | official_guidance | [page audit](https://www.ecologie.gouv.fr/politiques-publiques/audit-energetique-reglementaire) |
| `dvf_dataset_page` | data.gouv.fr / DGFiP | MÃ©thodologie et limites DVF | HTML | dataset_methodology | [DVF](https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres) |
| `ademe_dpe_dataset_page` | ADEME | SchÃ©ma, mÃ©thodologie, limites DPE | HTML | dataset_methodology | [DPE ADEME](https://data.ademe.fr/datasets/dpe03existant) |

Corpus dÃ©libÃ©rÃ©ment **petit** (6 ressources officielles), extensible.

## PortÃ©e temporelle

Les informations rÃ©glementaires Ã©voluent. Le registre supporte, quand
disponibles : date de publication, de mise Ã  jour, d'entrÃ©e/fin de vigueur, de
derniÃ¨re vÃ©rification. **Aucune date n'est inventÃ©e** : `null` quand
l'information fiable n'est pas prÃ©sente dans la source. Ã€ ce stade, seule
`last_verified_at` (2026-09-04) est renseignÃ©e ; les autres dÃ©pendent des dates
rÃ©elles publiÃ©es, Ã  confirmer lors de l'extraction (Phase 6.2).

## Raisons d'inclusion

- **DPE** : la grille Â« Comprendre mon DPE Â» et la page ministÃ©rielle couvrent la
  dÃ©finition, la mÃ©thode 3CL, les Ã©tiquettes et la validitÃ©.
- **Passoires / dÃ©cence / audit** : contraintes de location et de vente des
  logements F/G â€” cÅ“ur des questions rÃ©glementaires du projet.
- **DVF / DPE datasets** : mÃ©thodologie et **limites** des donnÃ©es, essentielles
  pour une interprÃ©tation honnÃªte.

## Limites connues

- Certaines pages ministÃ©rielles sont du **HTML** (contenu dynamique possible) ;
  l'extraction propre viendra en Phase 6.2.
- Les dates rÃ©glementaires prÃ©cises seront extraites des documents eux-mÃªmes.
- Le PDF Â« Comprendre mon DPE Â» est une grille de lecture, pas un texte normatif ;
  son `authority_level` est `official_guidance`, pas `normative_law`.

## Politique de mise Ã  jour

Le tÃ©lÃ©chargement est **idempotent** : un document au contenu inchangÃ© (mÃªme
SHA-256) est marquÃ© `unchanged` et n'est pas rÃ©Ã©crit. `--force` permet un
rafraÃ®chissement. Chaque rÃ©cupÃ©ration enregistre la provenance dans
`data/raw/documents/manifest.json` (ignorÃ© par Git).

## Citations et dates

Toute rÃ©ponse rÃ©glementaire future **devra afficher ses citations** (source,
lien officiel) et les **dates pertinentes** (entrÃ©e en vigueur, derniÃ¨re
vÃ©rification), pour rester vÃ©rifiable et honnÃªte.