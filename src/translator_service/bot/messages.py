import html
from pathlib import PurePath

from translator_service.documents import (
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedDocumentError,
)
from translator_service.extractors import TextExtractionError
from translator_service.job_runner import TranslationJob, TranslationJobStatus
from translator_service.bot_translation_service import PendingTranslation
from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    language_code_for_name,
    localized_language_name_for_code,
)
from translator_service.order_estimates import OrderEstimate


CONFIRM_TRANSLATION_TEXT = "Start Translation"
SUPPORTED_TRANSLATION_FORMATS = ("EPUB", "DOCX", "TXT")


# Beta FolioLoom interface. Keep copy centralized so adding another language is a
# matter of adding one locale block and the shared language registry entry.
MESSAGES = {
    "en": {
        "main_menu": [
            "📖 Translate a Book",
            "🧵 How It Works",
            "🌍 Language",
            "⚙️ Settings",
            "Help",
        ],
        "main_menu_button": "Main Menu",
        "start_title": "Welcome to FolioLoom.",
        "tagline": "Books, beautifully translated.",
        "start_body": (
            "Send a book, chapter, or manuscript, and I’ll help bring it into a "
            "new language while keeping its structure and voice intact."
        ),
        "permission_note": "Only upload texts you own or have permission to translate.",
        "formats": "Supported formats: {formats}.",
        "main_menu_title": "FolioLoom",
        "main_menu_prompt": "Choose what you’d like to do.",
        "upload_prompt": (
            "Send me a book, chapter, or manuscript.\n\n"
            "Supported formats: {formats}.\n\n"
            "I’ll read the file, prepare the text, and guide you through the translation."
        ),
        "help": (
            "Help\n\n"
            "FolioLoom translates books, chapters, and manuscripts into other languages.\n\n"
            "How it works:\n"
            "1. Send a supported file.\n"
            "2. Choose the target language.\n"
            "3. Confirm the settings.\n"
            "4. Download the translated result.\n\n"
            "For best results, use clean {formats} files and review the final translation before publishing.\n\n"
            "Only upload texts you own or have permission to translate."
        ),
        "how_it_works": (
            "How FolioLoom Works\n\n"
            "FolioLoom reads your book, keeps the structure, and prepares a translation into the language you choose.\n\n"
            "It is designed for books, chapters, manuscripts, and long-form texts.\n\n"
            "For publication-quality work, always review the final translation with an editor."
        ),
        "interface_language_prompt": "Language\n\nChoose interface language:",
        "interface_language_selected": "Interface language: {language_text}.",
        "settings_title": "Settings",
        "settings_body": "Choose how FolioLoom works for you.",
        "settings_preview": "Latest passage preview",
        "settings_preview_on": "On",
        "settings_preview_off": "Off",
        "settings_language": "Interface language",
        "hide_preview": "Hide Preview",
        "show_preview": "Show Preview",
        "translation_language_prompt": (
            "File received.\n\n"
            "Title: {file_name}\n"
            "Format: {file_format}\n"
            "{source_language_line}\n"
            "Choose the target language."
        ),
        "original_language": "Source language",
        "progress": "Translation progress",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "Turning the next page",
            "Keeping chapters in order",
            "The commas are behaving",
            "Following the author’s voice",
            "Preparing the next passage",
            "Working through the text",
        ),
        "back": "Back",
        "back_to_menu": "Returning to the Main menu.",
        "cancel": "Cancel",
        "cancel_hint": "To stop translation, press “{cancel_text}” or send /cancel.",
        "elapsed": "Elapsed",
        "time_left": "Time left",
        "estimated_time": "Estimated time",
        "time_unknown": "estimating",
        "last_fragment": "Last translated fragment",
        "cancel_requested": "Stopping translation after the current fragment.",
        "nothing_to_cancel": "There is no active translation to stop.",
        "no_pending_translation": "There is no translation waiting for confirmation.",
        "estimate_title": "Translation estimate",
        "document_ready": "Ready to begin.",
        "book": "Book",
        "file": "File",
        "format": "Format",
        "characters": "Characters",
        "fragments": "Fragments",
        "tokens": "Estimated tokens",
        "price": "Price",
        "from": "From",
        "to": "To",
        "preservation_note": "I’ll preserve chapters, paragraphs, and as much formatting as the current file allows.",
        "confirm_instruction": "Press “{confirm_text}” to start translation.",
        "queue_instruction": "Press “{confirm_text}” to queue translation.",
        "queued": "Your translation is queued: {file_name}.",
        "translating": "Your translation is in progress: {file_name}.",
        "ready": "Your translation is ready.\n\nYou can download the translated file below: {result_name}.",
        "cancelled": "Translation cancelled.\n\nPartial result: {result_name}.",
        "failed": "Something went wrong while translating.\n\nYour file is safe. Please try again, or return to the main menu.",
        "status": "Translation status: {status}",
        "confirm": "Start Translation",
        "unsupported_file": (
            "This file type is not supported yet.\n\n"
            "Please send one of these formats:\n{formats}"
        ),
        "file_too_large": (
            "This file is larger than the current limit of {limit}.\n\n"
            "Try sending a smaller file or splitting the book into chapters."
        ),
        "empty_file": "This file is empty. Please send a book, chapter, or manuscript with text.",
        "extraction_failed": (
            "I couldn’t read this file reliably.\n\n"
            "Try sending a cleaner copy, or use one of these formats:\n{formats}"
        ),
        "translation_failed": (
            "Something went wrong while translating.\n\n"
            "Your file is safe. Please try again, or return to the main menu."
        ),
        "unknown_text": (
            "Send a book, chapter, or manuscript to begin, or choose an option from the menu."
        ),
    },
    "ru": {
        "main_menu": [
            "📖 Перевести книгу",
            "🧵 Как это работает",
            "🌍 Язык",
            "⚙️ Настройки",
            "Помощь",
        ],
        "main_menu_button": "Главное меню",
        "start_title": "Добро пожаловать в FolioLoom.",
        "tagline": "Books, beautifully translated.",
        "start_body": (
            "Отправьте книгу, главу или рукопись — я помогу перевести текст на другой язык, "
            "сохранив структуру и голос автора."
        ),
        "permission_note": "Загружайте только тексты, которые принадлежат вам или на перевод которых у вас есть разрешение.",
        "formats": "Поддерживаемые форматы: {formats}.",
        "main_menu_title": "FolioLoom",
        "main_menu_prompt": "Выберите, что хотите сделать.",
        "upload_prompt": (
            "Отправьте книгу, главу или рукопись.\n\n"
            "Поддерживаемые форматы: {formats}.\n\n"
            "Я прочитаю файл, подготовлю текст и помогу выбрать настройки перевода."
        ),
        "help": (
            "Помощь\n\n"
            "FolioLoom переводит книги, главы и рукописи на другие языки.\n\n"
            "Как это работает:\n"
            "1. Отправьте поддерживаемый файл.\n"
            "2. Выберите язык перевода.\n"
            "3. Подтвердите настройки.\n"
            "4. Скачайте готовый перевод.\n\n"
            "Для лучшего результата используйте чистые файлы {formats} и проверьте перевод перед публикацией.\n\n"
            "Загружайте только тексты, которые принадлежат вам или на перевод которых у вас есть разрешение."
        ),
        "how_it_works": (
            "Как работает FolioLoom\n\n"
            "FolioLoom читает книгу, сохраняет структуру и готовит перевод на выбранный язык.\n\n"
            "Сервис создан для книг, глав, рукописей и длинных текстов.\n\n"
            "Для публикационного качества всегда проверяйте финальный перевод с редактором."
        ),
        "interface_language_prompt": "Язык\n\nВыберите язык интерфейса:",
        "interface_language_selected": "Язык интерфейса: {language_text}.",
        "settings_title": "Настройки",
        "settings_body": "Выберите, как FolioLoom будет работать для вас.",
        "settings_preview": "Последний фрагмент",
        "settings_preview_on": "включен",
        "settings_preview_off": "выключен",
        "settings_language": "Язык интерфейса",
        "hide_preview": "Скрыть фрагмент",
        "show_preview": "Показывать фрагмент",
        "translation_language_prompt": (
            "Файл получен.\n\n"
            "Название: {file_name}\n"
            "Формат: {file_format}\n"
            "{source_language_line}\n"
            "Теперь выберите язык перевода."
        ),
        "original_language": "Язык оригинала",
        "progress": "Прогресс перевода",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "Переворачиваю следующую страницу",
            "Главы остаются на своих местах",
            "Запятые ведут себя прилично",
            "Бережно веду голос автора",
            "Готовлю следующий фрагмент",
            "Перевожу текст",
        ),
        "back": "Назад",
        "back_to_menu": "Возвращаемся в главное меню.",
        "cancel": "Отмена",
        "cancel_hint": "Чтобы остановить перевод, нажмите «{cancel_text}» или отправьте /cancel.",
        "elapsed": "Прошло",
        "time_left": "Осталось",
        "estimated_time": "Примерное время",
        "time_unknown": "уточняется",
        "last_fragment": "Последний переведенный фрагмент",
        "cancel_requested": "Останавливаю перевод после текущего фрагмента.",
        "nothing_to_cancel": "Сейчас нет активного перевода для остановки.",
        "no_pending_translation": "Нет перевода, который ожидает подтверждения.",
        "estimate_title": "Оценка перевода",
        "document_ready": "Всё готово к переводу.",
        "book": "Книга",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символов",
        "fragments": "Фрагментов",
        "tokens": "Примерные токены",
        "price": "Цена",
        "from": "С языка",
        "to": "На язык",
        "preservation_note": "Я сохраню главы, абзацы и форматирование настолько, насколько позволяет исходный файл.",
        "confirm_instruction": "Нажмите «{confirm_text}», чтобы начать перевод.",
        "queue_instruction": "Нажмите «{confirm_text}», чтобы поставить перевод в очередь.",
        "queued": "Перевод в очереди: {file_name}.",
        "translating": "Перевод выполняется: {file_name}.",
        "ready": "Перевод готов.\n\nВы можете скачать файл ниже: {result_name}.",
        "cancelled": "Перевод отменен.\n\nЧастичный результат: {result_name}.",
        "failed": "Во время перевода что-то пошло не так.\n\nФайл не потерян. Попробуйте еще раз или вернитесь в главное меню.",
        "status": "Статус перевода: {status}",
        "confirm": "Начать перевод",
        "unsupported_file": (
            "Этот тип файла пока не поддерживается.\n\n"
            "Пожалуйста, отправьте файл одного из этих форматов:\n{formats}"
        ),
        "file_too_large": (
            "Файл больше текущего лимита: {limit}.\n\n"
            "Попробуйте отправить файл меньшего размера или разделить книгу на главы."
        ),
        "empty_file": "Этот файл пустой. Отправьте книгу, главу или рукопись с текстом.",
        "extraction_failed": (
            "Не получилось надежно прочитать этот файл.\n\n"
            "Попробуйте отправить более чистую копию или используйте один из этих форматов:\n{formats}"
        ),
        "translation_failed": (
            "Во время перевода что-то пошло не так.\n\n"
            "Файл не потерян. Попробуйте еще раз или вернитесь в главное меню."
        ),
        "unknown_text": (
            "Отправьте книгу, главу или рукопись, чтобы начать, или выберите действие в главном меню."
        ),
    },
}

for _language_code, _fallbacks in {
    "uk": {
        "main_menu": [
            "📖 Перекласти книгу",
            "🧵 Як це працює",
            "🌍 Мова",
            "⚙️ Налаштування",
            "Допомога",
        ],
        "main_menu_button": "Головне меню",
        "start_title": "Ласкаво просимо до FolioLoom.",
        "start_body": "Надішліть книгу, розділ або рукопис — я допоможу перекласти текст іншою мовою, зберігаючи структуру й голос автора.",
        "permission_note": "Завантажуйте лише тексти, які належать вам або які ви маєте право перекладати.",
        "main_menu_prompt": "Оберіть, що хочете зробити.",
        "upload_prompt": "Надішліть книгу, розділ або рукопис.\n\nПідтримувані формати: {formats}.\n\nЯ прочитаю файл, підготую текст і допоможу вибрати налаштування перекладу.",
        "interface_language_prompt": "Мова\n\nВиберіть мову інтерфейсу:",
        "interface_language_selected": "Мова інтерфейсу: {language_text}.",
        "settings_title": "Налаштування",
        "settings_body": "Оберіть, як FolioLoom працюватиме для вас.",
        "settings_preview": "Останній фрагмент",
        "settings_preview_on": "увімкнено",
        "settings_preview_off": "вимкнено",
        "settings_language": "Мова інтерфейсу",
        "hide_preview": "Сховати фрагмент",
        "show_preview": "Показувати фрагмент",
        "translation_language_prompt": "Файл отримано.\n\nНазва: {file_name}\nФормат: {file_format}\n{source_language_line}\nТепер виберіть мову перекладу.",
        "original_language": "Мова оригіналу",
        "back": "Назад",
        "back_to_menu": "Повертаємося до головного меню.",
        "cancel": "Скасувати",
        "confirm": "Почати переклад",
        "document_ready": "Усе готово до перекладу.",
        "from": "З мови",
        "to": "Мовою",
        "formats": "Підтримувані формати: {formats}.",
        "help": "Допомога\n\nFolioLoom перекладає книги, розділи та рукописи іншими мовами.\n\nЯк це працює:\n1. Надішліть підтримуваний файл.\n2. Виберіть мову перекладу.\n3. Підтвердьте налаштування.\n4. Завантажте готовий переклад.\n\nДля найкращого результату використовуйте чисті файли {formats} і перевіряйте фінальний переклад перед публікацією.\n\nЗавантажуйте лише тексти, які належать вам або які ви маєте право перекладати.",
        "how_it_works": "Як працює FolioLoom\n\nFolioLoom читає книгу, зберігає структуру й готує переклад вибраною мовою.\n\nСервіс створений для книг, розділів, рукописів і довгих текстів.\n\nДля публікаційної якості завжди перевіряйте фінальний переклад з редактором.",
        "progress": "Прогрес перекладу",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "Гортаю наступну сторінку",
            "Розділи тримаються купи",
            "Коми поводяться чемно",
            "Бережу голос автора",
            "Готую наступний фрагмент",
            "Перекладаю текст",
        ),
        "cancel_hint": "Щоб зупинити переклад, натисніть «{cancel_text}» або надішліть /cancel.",
        "elapsed": "Минуло",
        "time_left": "Залишилось",
        "estimated_time": "Орієнтовний час",
        "time_unknown": "уточнюється",
        "last_fragment": "Останній перекладений фрагмент",
        "cancel_requested": "Зупиняю переклад після поточного фрагмента.",
        "nothing_to_cancel": "Зараз немає активного перекладу для зупинки.",
        "no_pending_translation": "Немає перекладу, який очікує підтвердження.",
        "estimate_title": "Оцінка перекладу",
        "book": "Книга",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символів",
        "fragments": "Фрагментів",
        "tokens": "Орієнтовні токени",
        "price": "Ціна",
        "preservation_note": "Я збережу розділи, абзаци й форматування настільки, наскільки це дозволяє початковий файл.",
        "confirm_instruction": "Натисніть «{confirm_text}», щоб почати переклад.",
        "queue_instruction": "Натисніть «{confirm_text}», щоб поставити переклад у чергу.",
        "queued": "Переклад у черзі: {file_name}.",
        "translating": "Переклад виконується: {file_name}.",
        "ready": "Переклад готовий.\n\nВи можете завантажити файл нижче: {result_name}.",
        "cancelled": "Переклад скасовано.\n\nЧастковий результат: {result_name}.",
        "failed": "Під час перекладу щось пішло не так.\n\nФайл не втрачено. Спробуйте ще раз або поверніться до головного меню.",
        "status": "Статус перекладу: {status}",
        "unsupported_file": "Цей тип файлу поки не підтримується.\n\nБудь ласка, надішліть файл одного з цих форматів:\n{formats}",
        "file_too_large": "Файл більший за поточний ліміт: {limit}.\n\nСпробуйте надіслати менший файл або розділити книгу на глави.",
        "empty_file": "Цей файл порожній. Надішліть книгу, розділ або рукопис з текстом.",
        "extraction_failed": "Не вдалося надійно прочитати цей файл.\n\nСпробуйте надіслати чистішу копію або використайте один із цих форматів:\n{formats}",
        "translation_failed": "Під час перекладу щось пішло не так.\n\nФайл не втрачено. Спробуйте ще раз або поверніться до головного меню.",
        "unknown_text": "Надішліть книгу, розділ або рукопис, щоб почати, або виберіть дію в головному меню.",
    },
    "fr": {
        "main_menu": [
            "📖 Traduire un livre",
            "🧵 Fonctionnement",
            "🌍 Langue",
            "⚙️ Réglages",
            "Aide",
        ],
        "main_menu_button": "Menu principal",
        "start_title": "Bienvenue dans FolioLoom.",
        "start_body": "Envoyez un livre, un chapitre ou un manuscrit, et je vous aiderai à le porter dans une autre langue en préservant sa structure et sa voix.",
        "permission_note": "N’envoyez que des textes qui vous appartiennent ou que vous avez le droit de traduire.",
        "main_menu_prompt": "Choisissez ce que vous voulez faire.",
        "upload_prompt": "Envoyez-moi un livre, un chapitre ou un manuscrit.\n\nFormats pris en charge : {formats}.\n\nJe lirai le fichier, préparerai le texte et vous guiderai dans le choix de la langue.",
        "interface_language_prompt": "Langue\n\nChoisissez la langue de l’interface :",
        "interface_language_selected": "Langue de l’interface : {language_text}.",
        "settings_title": "Réglages",
        "settings_body": "Choisissez comment FolioLoom fonctionne pour vous.",
        "settings_preview": "Aperçu du dernier passage",
        "settings_preview_on": "activé",
        "settings_preview_off": "désactivé",
        "settings_language": "Langue de l’interface",
        "hide_preview": "Masquer l’aperçu",
        "show_preview": "Afficher l’aperçu",
        "translation_language_prompt": "Fichier reçu.\n\nTitre : {file_name}\nFormat : {file_format}\n{source_language_line}\nChoisissez maintenant la langue de traduction.",
        "original_language": "Langue source",
        "back": "Retour",
        "back_to_menu": "Retour au menu principal.",
        "cancel": "Annuler",
        "confirm": "Lancer la traduction",
        "document_ready": "Prêt à commencer.",
        "from": "Depuis",
        "to": "Vers",
        "formats": "Formats pris en charge : {formats}.",
        "help": "Aide\n\nFolioLoom traduit des livres, chapitres et manuscrits vers d’autres langues.\n\nFonctionnement :\n1. Envoyez un fichier pris en charge.\n2. Choisissez la langue cible.\n3. Confirmez les réglages.\n4. Téléchargez le résultat traduit.\n\nPour de meilleurs résultats, utilisez des fichiers {formats} propres et relisez la traduction avant publication.\n\nN’envoyez que des textes qui vous appartiennent ou que vous avez le droit de traduire.",
        "how_it_works": "Comment fonctionne FolioLoom\n\nFolioLoom lit votre livre, conserve sa structure et prépare une traduction dans la langue choisie.\n\nIl est conçu pour les livres, chapitres, manuscrits et textes longs.\n\nPour une qualité de publication, relisez toujours la traduction finale avec un éditeur.",
        "progress": "Progression de la traduction",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "Je tourne la page suivante",
            "Les chapitres restent en ordre",
            "Les virgules se tiennent bien",
            "Je garde le ton de l’auteur",
            "Je prépare le prochain passage",
            "Travail sur le texte",
        ),
        "cancel_hint": "Pour arrêter la traduction, appuyez sur « {cancel_text} » ou envoyez /cancel.",
        "elapsed": "Écoulé",
        "time_left": "Temps restant",
        "estimated_time": "Durée estimée",
        "time_unknown": "estimation en cours",
        "last_fragment": "Dernier fragment traduit",
        "cancel_requested": "J’arrête la traduction après le fragment en cours.",
        "nothing_to_cancel": "Aucune traduction active à arrêter.",
        "no_pending_translation": "Aucune traduction n’attend de confirmation.",
        "estimate_title": "Estimation de traduction",
        "book": "Livre",
        "file": "Fichier",
        "format": "Format",
        "characters": "Caractères",
        "fragments": "Fragments",
        "tokens": "Jetons estimés",
        "price": "Prix",
        "preservation_note": "Je préserverai les chapitres, paragraphes et autant de mise en forme que le fichier le permet.",
        "confirm_instruction": "Appuyez sur « {confirm_text} » pour lancer la traduction.",
        "queue_instruction": "Appuyez sur « {confirm_text} » pour mettre la traduction en file d’attente.",
        "queued": "Votre traduction est en file d’attente : {file_name}.",
        "translating": "Votre traduction est en cours : {file_name}.",
        "ready": "Votre traduction est prête.\n\nVous pouvez télécharger le fichier ci-dessous : {result_name}.",
        "cancelled": "Traduction annulée.\n\nRésultat partiel : {result_name}.",
        "failed": "Un problème est survenu pendant la traduction.\n\nVotre fichier est en sécurité. Réessayez ou revenez au menu principal.",
        "status": "Statut de la traduction : {status}",
        "unsupported_file": "Ce type de fichier n’est pas encore pris en charge.\n\nVeuillez envoyer l’un de ces formats :\n{formats}",
        "file_too_large": "Ce fichier dépasse la limite actuelle de {limit}.\n\nEssayez un fichier plus petit ou divisez le livre en chapitres.",
        "empty_file": "Ce fichier est vide. Envoyez un livre, un chapitre ou un manuscrit contenant du texte.",
        "extraction_failed": "Je n’ai pas pu lire ce fichier de façon fiable.\n\nEssayez une copie plus propre ou utilisez l’un de ces formats :\n{formats}",
        "translation_failed": "Un problème est survenu pendant la traduction.\n\nVotre fichier est en sécurité. Réessayez ou revenez au menu principal.",
        "unknown_text": "Envoyez un livre, un chapitre ou un manuscrit pour commencer, ou choisissez une option dans le menu principal.",
    },
    "es": {
        "main_menu": [
            "📖 Traducir un libro",
            "🧵 Cómo funciona",
            "🌍 Idioma",
            "⚙️ Ajustes",
            "Ayuda",
        ],
        "main_menu_button": "Menú principal",
        "start_title": "Bienvenido a FolioLoom.",
        "start_body": "Envía un libro, capítulo o manuscrito y te ayudaré a llevarlo a otro idioma conservando su estructura y su voz.",
        "permission_note": "Sube solo textos que te pertenezcan o que tengas permiso para traducir.",
        "main_menu_prompt": "Elige qué quieres hacer.",
        "upload_prompt": "Envíame un libro, capítulo o manuscrito.\n\nFormatos admitidos: {formats}.\n\nLeeré el archivo, prepararé el texto y te guiaré por la traducción.",
        "interface_language_prompt": "Idioma\n\nElige el idioma de la interfaz:",
        "interface_language_selected": "Idioma de la interfaz: {language_text}.",
        "settings_title": "Ajustes",
        "settings_body": "Elige cómo FolioLoom funciona para ti.",
        "settings_preview": "Vista del último pasaje",
        "settings_preview_on": "activada",
        "settings_preview_off": "desactivada",
        "settings_language": "Idioma de la interfaz",
        "hide_preview": "Ocultar vista",
        "show_preview": "Mostrar vista",
        "translation_language_prompt": "Archivo recibido.\n\nTítulo: {file_name}\nFormato: {file_format}\n{source_language_line}\nAhora elige el idioma de traducción.",
        "original_language": "Idioma original",
        "back": "Atrás",
        "back_to_menu": "Volvemos al menú principal.",
        "cancel": "Cancelar",
        "confirm": "Iniciar traducción",
        "document_ready": "Todo listo para empezar.",
        "from": "Desde",
        "to": "A",
        "formats": "Formatos admitidos: {formats}.",
        "help": "Ayuda\n\nFolioLoom traduce libros, capítulos y manuscritos a otros idiomas.\n\nCómo funciona:\n1. Envía un archivo admitido.\n2. Elige el idioma de destino.\n3. Confirma los ajustes.\n4. Descarga el resultado traducido.\n\nPara obtener mejores resultados, usa archivos {formats} limpios y revisa la traducción final antes de publicarla.\n\nSube solo textos que te pertenezcan o que tengas permiso para traducir.",
        "how_it_works": "Cómo funciona FolioLoom\n\nFolioLoom lee tu libro, conserva la estructura y prepara una traducción al idioma que elijas.\n\nEstá diseñado para libros, capítulos, manuscritos y textos largos.\n\nPara calidad de publicación, revisa siempre la traducción final con un editor.",
        "progress": "Progreso de traducción",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "Pasando la siguiente página",
            "Los capítulos siguen en orden",
            "Las comas se portan bien",
            "Cuidando la voz del autor",
            "Preparando el siguiente pasaje",
            "Trabajando el texto",
        ),
        "cancel_hint": "Para detener la traducción, pulsa «{cancel_text}» o envía /cancel.",
        "elapsed": "Transcurrido",
        "time_left": "Restante",
        "estimated_time": "Tiempo estimado",
        "time_unknown": "calculando",
        "last_fragment": "Último fragmento traducido",
        "cancel_requested": "Detendré la traducción después del fragmento actual.",
        "nothing_to_cancel": "No hay una traducción activa para detener.",
        "no_pending_translation": "No hay ninguna traducción esperando confirmación.",
        "estimate_title": "Estimación de traducción",
        "book": "Libro",
        "file": "Archivo",
        "format": "Formato",
        "characters": "Caracteres",
        "fragments": "Fragmentos",
        "tokens": "Tokens estimados",
        "price": "Precio",
        "preservation_note": "Conservaré capítulos, párrafos y tanto formato como permita el archivo actual.",
        "confirm_instruction": "Pulsa «{confirm_text}» para iniciar la traducción.",
        "queue_instruction": "Pulsa «{confirm_text}» para poner la traducción en cola.",
        "queued": "Tu traducción está en cola: {file_name}.",
        "translating": "Tu traducción está en curso: {file_name}.",
        "ready": "Tu traducción está lista.\n\nPuedes descargar el archivo abajo: {result_name}.",
        "cancelled": "Traducción cancelada.\n\nResultado parcial: {result_name}.",
        "failed": "Algo salió mal durante la traducción.\n\nTu archivo está a salvo. Inténtalo de nuevo o vuelve al menú principal.",
        "status": "Estado de traducción: {status}",
        "unsupported_file": "Este tipo de archivo aún no es compatible.\n\nEnvía uno de estos formatos:\n{formats}",
        "file_too_large": "Este archivo supera el límite actual de {limit}.\n\nPrueba con un archivo más pequeño o divide el libro en capítulos.",
        "empty_file": "Este archivo está vacío. Envía un libro, capítulo o manuscrito con texto.",
        "extraction_failed": "No pude leer este archivo de forma fiable.\n\nPrueba con una copia más limpia o usa uno de estos formatos:\n{formats}",
        "translation_failed": "Algo salió mal durante la traducción.\n\nTu archivo está a salvo. Inténtalo de nuevo o vuelve al menú principal.",
        "unknown_text": "Envía un libro, capítulo o manuscrito para empezar, o elige una opción del menú principal.",
    },
    "nl": {
        "main_menu": [
            "📖 Boek vertalen",
            "🧵 Zo werkt het",
            "🌍 Taal",
            "⚙️ Instellingen",
            "Hulp",
        ],
        "main_menu_button": "Hoofdmenu",
        "start_title": "Welkom bij FolioLoom.",
        "start_body": "Stuur een boek, hoofdstuk of manuscript, dan help ik het naar een nieuwe taal te brengen met behoud van structuur en stem.",
        "permission_note": "Upload alleen teksten die van jou zijn of waarvoor je toestemming hebt om ze te vertalen.",
        "main_menu_prompt": "Kies wat je wilt doen.",
        "upload_prompt": "Stuur me een boek, hoofdstuk of manuscript.\n\nOndersteunde formaten: {formats}.\n\nIk lees het bestand, bereid de tekst voor en begeleid je door de vertaling.",
        "interface_language_prompt": "Taal\n\nKies de interfacetaal:",
        "interface_language_selected": "Interfacetaal: {language_text}.",
        "settings_title": "Instellingen",
        "settings_body": "Kies hoe FolioLoom voor jou werkt.",
        "settings_preview": "Voorbeeld van laatste passage",
        "settings_preview_on": "aan",
        "settings_preview_off": "uit",
        "settings_language": "Interfacetaal",
        "hide_preview": "Voorbeeld verbergen",
        "show_preview": "Voorbeeld tonen",
        "translation_language_prompt": "Bestand ontvangen.\n\nTitel: {file_name}\nFormaat: {file_format}\n{source_language_line}\nKies nu de taal waarnaar je wilt vertalen.",
        "original_language": "Brontaal",
        "back": "Terug",
        "back_to_menu": "Terug naar het Hoofdmenu.",
        "cancel": "Annuleren",
        "confirm": "Vertaling starten",
        "document_ready": "Klaar om te beginnen.",
        "from": "Van",
        "to": "Naar",
        "formats": "Ondersteunde formaten: {formats}.",
        "help": "Hulp\n\nFolioLoom vertaalt boeken, hoofdstukken en manuscripten naar andere talen.\n\nZo werkt het:\n1. Stuur een ondersteund bestand.\n2. Kies de doeltaal.\n3. Bevestig de instellingen.\n4. Download het vertaalde resultaat.\n\nGebruik voor het beste resultaat schone {formats}-bestanden en controleer de vertaling voor publicatie.\n\nUpload alleen teksten die van jou zijn of waarvoor je toestemming hebt om ze te vertalen.",
        "how_it_works": "Zo werkt FolioLoom\n\nFolioLoom leest je boek, behoudt de structuur en maakt een vertaling in de taal die je kiest.\n\nHet is ontworpen voor boeken, hoofdstukken, manuscripten en lange teksten.\n\nVoor publicatiekwaliteit: laat de eindvertaling altijd nakijken door een redacteur.",
        "progress": "Vertaalvoortgang",
        "activity": "{phrase} {indicator}",
        "activity_phrases": (
            "De volgende bladzijde draait",
            "De hoofdstukken blijven op volgorde",
            "De komma’s gedragen zich",
            "De stem van de auteur blijft dichtbij",
            "De volgende passage wordt voorbereid",
            "Aan de tekst werken",
        ),
        "cancel_hint": "Om de vertaling te stoppen, druk op “{cancel_text}” of stuur /cancel.",
        "elapsed": "Verstreken",
        "time_left": "Resterende tijd",
        "estimated_time": "Geschatte tijd",
        "time_unknown": "wordt geschat",
        "last_fragment": "Laatste vertaalde fragment",
        "cancel_requested": "Ik stop de vertaling na het huidige fragment.",
        "nothing_to_cancel": "Er is nu geen actieve vertaling om te stoppen.",
        "no_pending_translation": "Er wacht geen vertaling op bevestiging.",
        "estimate_title": "Vertaalinschatting",
        "book": "Boek",
        "file": "Bestand",
        "format": "Formaat",
        "characters": "Tekens",
        "fragments": "Fragmenten",
        "tokens": "Geschatte tokens",
        "price": "Prijs",
        "preservation_note": "Ik behoud hoofdstukken, alinea’s en zoveel opmaak als het huidige bestand toelaat.",
        "confirm_instruction": "Druk op “{confirm_text}” om de vertaling te starten.",
        "queue_instruction": "Druk op “{confirm_text}” om de vertaling in de wachtrij te zetten.",
        "queued": "Je vertaling staat in de wachtrij: {file_name}.",
        "translating": "Je vertaling wordt uitgevoerd: {file_name}.",
        "ready": "Je vertaling is klaar.\n\nJe kunt het bestand hieronder downloaden: {result_name}.",
        "cancelled": "Vertaling geannuleerd.\n\nGedeeltelijk resultaat: {result_name}.",
        "failed": "Er ging iets mis tijdens het vertalen.\n\nJe bestand is veilig. Probeer het opnieuw of ga terug naar het hoofdmenu.",
        "status": "Vertaalstatus: {status}",
        "unsupported_file": "Dit bestandstype wordt nog niet ondersteund.\n\nStuur een van deze formaten:\n{formats}",
        "file_too_large": "Dit bestand is groter dan de huidige limiet van {limit}.\n\nProbeer een kleiner bestand of splits het boek in hoofdstukken.",
        "empty_file": "Dit bestand is leeg. Stuur een boek, hoofdstuk of manuscript met tekst.",
        "extraction_failed": "Ik kon dit bestand niet betrouwbaar lezen.\n\nProbeer een schonere kopie of gebruik een van deze formaten:\n{formats}",
        "translation_failed": "Er ging iets mis tijdens het vertalen.\n\nJe bestand is veilig. Probeer het opnieuw of ga terug naar het hoofdmenu.",
        "unknown_text": "Stuur een boek, hoofdstuk of manuscript om te beginnen, of kies een optie in het Hoofdmenu.",
    },
}.items():
    MESSAGES[_language_code] = {**MESSAGES["en"], **_fallbacks}


def build_main_menu(interface_language: str = "en") -> list[str]:
    return list(_messages(interface_language)["main_menu"])


def build_start_message(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    menu_lines = "\n".join(f"- {item}" for item in build_main_menu(interface_language))
    return (
        f"{messages['start_title']}\n\n"
        f"{messages['tagline']}\n\n"
        f"{messages['start_body']}\n\n"
        f"{messages['permission_note']}\n\n"
        f"{messages['formats'].format(formats=_supported_formats_text())}\n\n"
        f"{messages['main_menu_title']}\n"
        f"{messages['main_menu_prompt']}\n{menu_lines}"
    )


def get_main_menu_text(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    return f"{messages['main_menu_title']}\n\n{messages['main_menu_prompt']}"


def build_upload_prompt_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["upload_prompt"].format(
        formats=_supported_formats_text()
    )


def build_help_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["help"].format(
        formats=_supported_formats_text()
    )


def build_how_it_works_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["how_it_works"]


def build_unknown_text_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["unknown_text"]


def build_settings_message(
    *,
    interface_language: str = "en",
    progress_preview_enabled: bool = True,
) -> str:
    messages = _messages(interface_language)
    preview_status = (
        messages["settings_preview_on"]
        if progress_preview_enabled
        else messages["settings_preview_off"]
    )
    language_name = localized_language_name_for_code(
        interface_language,
        interface_language,
    )
    return (
        f"{messages['settings_title']}\n\n"
        f"{messages['settings_body']}\n\n"
        f"{messages['settings_preview']}: {preview_status}\n"
        f"{messages['settings_language']}: {language_name}"
    )


def build_language_selection_message(interface_language: str = "en") -> str:
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    return f"{_messages(interface_language)['interface_language_prompt']}\n{language_lines}"


def build_language_selected_message(
    language_text: str,
    interface_language: str = "en",
) -> str:
    return _messages(interface_language)["interface_language_selected"].format(
        language_text=language_text
    )


def build_translation_language_selection_message(
    file_name: str,
    interface_language: str = "en",
    source_language_display: str | None = None,
) -> str:
    messages = _messages(interface_language)
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    source_language_line = (
        f"{messages['original_language']}: {_localized_source_language_display_text(source_language_display, 'auto', interface_language)}\n"
        if source_language_display
        else ""
    )
    return (
        messages["translation_language_prompt"].format(
            file_name=file_name,
            file_format=_file_format_label(file_name),
            source_language_line=source_language_line,
        )
        + f"\n{language_lines}"
    )


def build_order_estimate_message(
    estimate: OrderEstimate,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    return (
        f"{messages['estimate_title']}\n\n"
        f"{messages['file']}: {estimate.file_name}\n"
        f"{messages['format']}: {estimate.document_format.value.upper()}\n"
        f"{messages['characters']}: {estimate.character_count}\n"
        f"{messages['fragments']}: {estimate.fragment_count}\n"
        f"{messages['price']}: ${estimate.price_usd:.2f}\n\n"
        f"{messages['queue_instruction'].format(confirm_text=confirm_text)}"
    )


def build_pending_translation_message(
    pending: PendingTranslation,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    return (
        f"{messages['document_ready']}\n\n"
        f"{messages['book']}: {pending.file_name}\n"
        f"{messages['from']}: {_localized_source_language_display_text(pending.source_language_display, pending.source_language, interface_language)}\n"
        f"{messages['to']}: {localized_language_name_for_code(pending.target_language, interface_language)}\n"
        f"{messages['fragments']}: {pending.fragment_count}\n"
        f"{messages['estimated_time']}: {_format_duration(pending.estimated_seconds or 0, interface_language)}\n"
        f"{messages['price']}: ${pending.price_usd:.2f}\n\n"
        f"{messages['preservation_note']}\n\n"
        f"{messages['confirm_instruction'].format(confirm_text=confirm_text)}"
    )


def is_confirm_translation_text(text: str | None) -> bool:
    if text is None:
        return False

    normalized = text.strip().lower()
    localized_confirm_texts = {
        messages["confirm"].lower() for messages in MESSAGES.values()
    }
    legacy_confirm_texts = {
        "подтвердить",
        "підтвердити",
        "confirmer",
        "confirmar",
        "confirm",
        "bevestigen",
    }
    return normalized in localized_confirm_texts | legacy_confirm_texts | {"/confirm"}


def is_translate_book_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 0)


def is_how_it_works_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 1)


def is_language_menu_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 2)


def is_settings_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 3)


def is_help_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 4)


def is_toggle_progress_preview_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {
        messages[key].lower()
        for messages in MESSAGES.values()
        for key in ("hide_preview", "show_preview")
    }


def is_main_menu_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {
        messages["main_menu_button"].lower() for messages in MESSAGES.values()
    }


def is_back_text(text: str | None) -> bool:
    return _matches_localized_text(text, "back")


def is_cancel_text(text: str | None) -> bool:
    return _matches_localized_text(text, "cancel") or _normalize_text(text) == "/cancel"


def build_translation_progress_message(
    *,
    completed_fragments: int,
    total_fragments: int,
    interface_language: str = "en",
    estimated_total_seconds: int | None = None,
    elapsed_seconds: int | None = None,
    last_translated_text: str | None = None,
    activity_indicator: str = "⠋",
    activity_phrase_index: int = 5,
) -> str:
    messages = _messages(interface_language)
    safe_total = max(total_fragments, 1)
    percent = min(100, round(completed_fragments / safe_total * 100))
    filled_cells = min(10, percent // 10)
    bar = "#" * filled_cells + "-" * (10 - filled_cells)
    elapsed_line = ""
    if elapsed_seconds is not None:
        elapsed_line = f"\n{messages['elapsed']}: {_format_duration(elapsed_seconds, interface_language)}"

    time_left = messages["time_unknown"]
    if estimated_total_seconds is not None and elapsed_seconds is not None:
        remaining_seconds = max(0, estimated_total_seconds - elapsed_seconds)
        time_left = f"~{_format_duration(remaining_seconds, interface_language)}"

    last_fragment_line = ""
    if last_translated_text:
        last_fragment_line = (
            f"{messages['last_fragment']}:\n"
            f"<blockquote expandable>{html.escape(_shorten_progress_fragment(last_translated_text))}</blockquote>"
        )
    last_fragment_section = f"\n\n{last_fragment_line}" if last_fragment_line else ""

    return (
        f"{messages['progress']}: [{bar}] "
        f"{completed_fragments}/{total_fragments} ({percent}%)"
        f"{elapsed_line}\n"
        f"{messages['time_left']}: {time_left}"
        f"\n{messages['activity'].format(phrase=get_progress_activity_phrase(interface_language, activity_phrase_index), indicator=activity_indicator)}"
        f"{last_fragment_section}\n\n"
        f"{build_cancel_hint_message(interface_language)}"
    )


def build_cancel_requested_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["cancel_requested"]


def get_progress_activity_phrase(
    interface_language: str = "en",
    phrase_index: int = 0,
) -> str:
    phrases = _messages(interface_language)["activity_phrases"]
    return phrases[phrase_index % len(phrases)]


def build_nothing_to_cancel_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["nothing_to_cancel"]


def build_no_pending_translation_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["no_pending_translation"]


def build_back_to_menu_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["back_to_menu"]


def build_cancel_hint_message(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    return messages["cancel_hint"].format(cancel_text=messages["cancel"])


def _format_duration(seconds: int, interface_language: str = "en") -> str:
    safe_seconds = max(0, round(seconds))
    minutes, remaining_seconds = divmod(safe_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    units = _time_units(interface_language)

    if hours:
        return f"{hours} {units['hour']} {remaining_minutes} {units['minute']}"
    if minutes:
        return f"{minutes} {units['minute']} {remaining_seconds} {units['second']}"
    return f"{remaining_seconds} {units['second']}"


def _shorten_progress_fragment(text: str, max_length: int = 500) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def get_back_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["back"]


def get_cancel_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["cancel"]


def build_translation_job_status_message(
    job: TranslationJob,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    if job.status is TranslationJobStatus.QUEUED:
        return messages["queued"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.TRANSLATING:
        return messages["translating"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.READY:
        result_name = job.result_file_name or "результат"
        return messages["ready"].format(result_name=result_name)

    if job.status is TranslationJobStatus.FAILED:
        return messages["failed"]

    if job.status is TranslationJobStatus.CANCELLED:
        result_name = job.result_file_name or "partial result"
        return messages["cancelled"].format(result_name=result_name)

    return messages["status"].format(status=job.status.value)


def get_confirm_translation_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["confirm"]


def get_main_menu_button_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["main_menu_button"]


def get_toggle_progress_preview_text(
    interface_language: str = "en",
    progress_preview_enabled: bool = True,
) -> str:
    key = "hide_preview" if progress_preview_enabled else "show_preview"
    return _messages(interface_language)[key]


def build_upload_error_message(error: Exception, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    if isinstance(error, UnsupportedDocumentError):
        return messages["unsupported_file"].format(formats=_supported_formats_lines())
    if isinstance(error, ValueError) and "TXT, DOCX, and EPUB" in str(error):
        return messages["unsupported_file"].format(formats=_supported_formats_lines())
    if isinstance(error, FileTooLargeError):
        return messages["file_too_large"].format(limit=_upload_limit_from_error(error))
    if isinstance(error, EmptyDocumentError):
        return messages["empty_file"]
    if isinstance(error, TextExtractionError):
        return messages["extraction_failed"].format(formats=_supported_formats_lines())
    return messages["translation_failed"]


def _messages(interface_language: str) -> dict:
    return MESSAGES.get(interface_language, MESSAGES["en"])


def _time_units(interface_language: str) -> dict[str, str]:
    return {
        "en": {"hour": "h", "minute": "min", "second": "sec"},
        "ru": {"hour": "ч", "minute": "мин", "second": "сек"},
        "uk": {"hour": "год", "minute": "хв", "second": "с"},
        "fr": {"hour": "h", "minute": "min", "second": "s"},
        "es": {"hour": "h", "minute": "min", "second": "s"},
        "nl": {"hour": "u", "minute": "min", "second": "sec"},
    }.get(interface_language, {"hour": "h", "minute": "min", "second": "sec"})


def _localized_source_language_display_text(
    source_language_display: str | None,
    source_language: str,
    interface_language: str,
) -> str:
    display = source_language_display
    if not display:
        return localized_language_name_for_code(source_language, interface_language)

    normalized = display.strip()
    if normalized.lower().startswith("auto"):
        auto_text = localized_language_name_for_code("auto", interface_language)
        if "(" not in normalized or not normalized.endswith(")"):
            return auto_text
        detail = normalized.split("(", 1)[1][:-1].strip()
        if detail.lower().startswith("mixed:"):
            names = detail.split(":", 1)[1]
            localized_names = [
                _localized_name_from_display_name(name.strip(), interface_language)
                for name in names.split(",")
                if name.strip()
            ]
            mixed_text = localized_language_name_for_code("mixed", interface_language)
            return f"{auto_text} ({mixed_text}: {', '.join(localized_names)})"
        return f"{auto_text} ({_localized_name_from_display_name(detail, interface_language)})"

    return _localized_name_from_display_name(normalized, interface_language)


def _localized_name_from_display_name(
    language_name: str,
    interface_language: str,
) -> str:
    language_code = language_code_for_name(language_name)
    if language_code is None:
        return language_name
    return localized_language_name_for_code(language_code, interface_language)


def _matches_localized_text(text: str | None, key: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {messages[key].lower() for messages in MESSAGES.values()}


def _normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    return text.strip().lower()


def _matches_main_menu_item(text: str | None, item_index: int) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return normalized in {
        messages["main_menu"][item_index].lower() for messages in MESSAGES.values()
    }


def _supported_formats_text() -> str:
    return ", ".join(SUPPORTED_TRANSLATION_FORMATS)


def _supported_formats_lines() -> str:
    return "\n".join(SUPPORTED_TRANSLATION_FORMATS)


def _file_format_label(file_name: str) -> str:
    extension = PurePath(file_name).suffix.lower().lstrip(".")
    return extension.upper() if extension else "unknown"


def _upload_limit_from_error(error: Exception) -> str:
    message = str(error)
    marker = "of "
    if marker in message and message.endswith(" MB"):
        return message.split(marker, 1)[1]
    return "50 MB"
