#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx One-Click Install v8
# Usage: curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
# i18n: MESHCTX_LANG=zh|en|ja|ko|fr|de|es|it|ar (default: auto from LANG env)
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
BOLD='\033[1m'

# ── i18n ─────────────────────────────────────────────
detect_lang() {
    if [ -n "$MESHCTX_LANG" ]; then echo "$MESHCTX_LANG"; return; fi
    # 默认统一英文显示；如需其他语言显式设置 MESHCTX_LANG=zh|ja|...
    echo "en"
}
LANG_CHOICE=$(detect_lang)
T() {
    case "$1" in
    header_installer)
        case "$LANG_CHOICE" in
            zh) echo "meshctx v${VERSION} 一键安装" ;;
            en) echo "meshctx v${VERSION} One-Click Install" ;;
            ja) echo "meshctx v${VERSION} ワンクリックインストール" ;;
            ko) echo "meshctx v${VERSION} 원클릭 설치" ;;
            fr) echo "meshctx v${VERSION} Installation en un clic" ;;
            de) echo "meshctx v${VERSION} Ein-Klick-Installation" ;;
            es) echo "meshctx v${VERSION} Instalación en un clic" ;;
            it) echo "meshctx v${VERSION} Installazione con un clic" ;;
            ar) echo "meshctx v${VERSION} تثبيت بنقرة واحدة" ;;
            ru) echo "meshctx v${VERSION} установка в один клик" ;;
        esac
        ;;
    step_stop)
        case "$LANG_CHOICE" in
            zh) echo '停止旧版本...' ;;
            en) echo 'Stopping old version...' ;;
            ja) echo '古いバージョンを停止中...' ;;
            ko) echo '이전 버전 중지 중...' ;;
            fr) echo 'Arrêt de l'\''ancienne version...' ;;
            de) echo 'Alte Version wird beendet...' ;;
            es) echo 'Deteniendo versión anterior...' ;;
            it) echo 'Arresto della versione precedente...' ;;
            ar) echo 'إيقاف الإصدار القديم...' ;;
            ru) echo 'Остановка старой версии...' ;;
        esac
        ;;
    stopped_ok)
        case "$LANG_CHOICE" in
            zh) echo "已停止旧服务并释放端口 ${PORT}" ;;
            en) echo "Stopped old service, freed port ${PORT}" ;;
            ja) echo "古いサービスを停止し、ポート ${PORT} を解放しました" ;;
            ko) echo "이전 서비스 중지 및 포트 ${PORT} 해제됨" ;;
            fr) echo "Ancien service arrêté, port ${PORT} libéré" ;;
            de) echo "Alter Dienst beendet, Port ${PORT} freigegeben" ;;
            es) echo "Servicio anterior detenido, puerto ${PORT} liberado" ;;
            it) echo "Vecchio servizio arrestato, porta ${PORT} liberata" ;;
            ar) echo "تم إيقاف الخدمة القديمة وتحرير المنفذ ${PORT}" ;;
            ru) echo "Старая служба остановлена, порт ${PORT} освобождён" ;;
        esac
        ;;
    no_stop_needed)
        case "$LANG_CHOICE" in
            zh) echo '无需停止' ;;
            en) echo 'No stop needed' ;;
            ja) echo '停止不要' ;;
            ko) echo '중지 불필요' ;;
            fr) echo 'Aucun arrêt nécessaire' ;;
            de) echo 'Kein Stopp erforderlich' ;;
            es) echo 'No es necesario detener' ;;
            it) echo 'Nessun arresto necessario' ;;
            ar) echo 'لا حاجة للإيقاف' ;;
            ru) echo 'Останавливать не требуется' ;;
        esac
        ;;
    step_check)
        case "$LANG_CHOICE" in
            zh) echo '检查环境...' ;;
            en) echo 'Checking environment...' ;;
            ja) echo '環境を確認中...' ;;
            ko) echo '환경 확인 중...' ;;
            fr) echo 'Vérification de l'\''environnement...' ;;
            de) echo 'Umgebung wird geprüft...' ;;
            es) echo 'Comprobando entorno...' ;;
            it) echo 'Verifica dell'\''ambiente in corso...' ;;
            ar) echo 'التحقق من البيئة...' ;;
            ru) echo 'Проверка окружения...' ;;
        esac
        ;;
    need_python)
        case "$LANG_CHOICE" in
            zh) echo '需要 Python 3.10+，请先安装: apt install python3' ;;
            en) echo 'Requires Python 3.10+, install: apt install python3' ;;
            ja) echo 'Python 3.10+ が必要です。インストール: apt install python3' ;;
            ko) echo 'Python 3.10+ 필요, 설치: apt install python3' ;;
            fr) echo 'Python 3.10+ requis, installez: apt install python3' ;;
            de) echo 'Python 3.10+ erforderlich, installieren: apt install python3' ;;
            es) echo 'Requiere Python 3.10+, instale: apt install python3' ;;
            it) echo 'Richiede Python 3.10+, installa: apt install python3' ;;
            ar) echo 'يتطلب Python 3.10+، ثبّت: apt install python3' ;;
            ru) echo 'Требуется Python 3.10+, установите: apt install python3' ;;
        esac
        ;;
    need_python_ver)
        case "$LANG_CHOICE" in
            zh) echo "需要 Python 3.10+，当前 ${PY_VER}" ;;
            en) echo "Requires Python 3.10+, current ${PY_VER}" ;;
            ja) echo "Python 3.10+ が必要です。現在 ${PY_VER}" ;;
            ko) echo "Python 3.10+ 필요, 현재 ${PY_VER}" ;;
            fr) echo "Python 3.10+ requis, actuel ${PY_VER}" ;;
            de) echo "Python 3.10+ erforderlich, aktuell ${PY_VER}" ;;
            es) echo "Requiere Python 3.10+, actual ${PY_VER}" ;;
            it) echo "Richiede Python 3.10+, attuale ${PY_VER}" ;;
            ar) echo "يتطلب Python 3.10+، الإصدار الحالي ${PY_VER}" ;;
            ru) echo "Требуется Python 3.10+, текущая версия ${PY_VER}" ;;
        esac
        ;;
    step_download)
        case "$LANG_CHOICE" in
            zh) echo "下载 meshctx v${VERSION}..." ;;
            en) echo "Downloading meshctx v${VERSION}..." ;;
            ja) echo "meshctx v${VERSION} をダウンロード中..." ;;
            ko) echo "meshctx v${VERSION} 다운로드 중..." ;;
            fr) echo "Téléchargement de meshctx v${VERSION}..." ;;
            de) echo "meshctx v${VERSION} wird heruntergeladen..." ;;
            es) echo "Descargando meshctx v${VERSION}..." ;;
            it) echo "Scaricamento di meshctx v${VERSION} in corso..." ;;
            ar) echo "جاري تنزيل meshctx v${VERSION}..." ;;
            ru) echo "Скачивание meshctx v${VERSION}..." ;;
        esac
        ;;
    download_ok)
        case "$LANG_CHOICE" in
            zh) echo '下载完成' ;;
            en) echo 'Download complete' ;;
            ja) echo 'ダウンロード完了' ;;
            ko) echo '다운로드 완료' ;;
            fr) echo 'Téléchargement terminé' ;;
            de) echo 'Download abgeschlossen' ;;
            es) echo 'Descarga completa' ;;
            it) echo 'Download completato' ;;
            ar) echo 'اكتمل التنزيل' ;;
            ru) echo 'Скачивание завершено' ;;
        esac
        ;;
    download_fail)
        case "$LANG_CHOICE" in
            zh) echo '下载失败' ;;
            en) echo 'Download failed' ;;
            ja) echo 'ダウンロード失敗' ;;
            ko) echo '다운로드 실패' ;;
            fr) echo 'Échec du téléchargement' ;;
            de) echo 'Download fehlgeschlagen' ;;
            es) echo 'Descarga fallida' ;;
            it) echo 'Download fallito' ;;
            ar) echo 'فشل التنزيل' ;;
            ru) echo 'Ошибка скачивания' ;;
        esac
        ;;
    download_fail_hint)
        case "$LANG_CHOICE" in
            zh) echo '请检查网络连接，或手动下载:' ;;
            en) echo 'Check network, or download manually:' ;;
            ja) echo 'ネットワークを確認するか、手動でダウンロードしてください:' ;;
            ko) echo '네트워크를 확인하거나 수동으로 다운로드하세요:' ;;
            fr) echo 'Vérifiez le réseau ou téléchargez manuellement:' ;;
            de) echo 'Netzwerk prüfen oder manuell herunterladen:' ;;
            es) echo 'Verifique la red o descargue manualmente:' ;;
            it) echo 'Controlla la rete o scarica manualmente:' ;;
            ar) echo 'تحقق من الشبكة أو نزّل يدوياً:' ;;
            ru) echo 'Проверьте сеть или скачайте вручную:' ;;
        esac
        ;;
    step_install)
        case "$LANG_CHOICE" in
            zh) echo '安装中...' ;;
            en) echo 'Installing...' ;;
            ja) echo 'インストール中...' ;;
            ko) echo '설치 중...' ;;
            fr) echo 'Installation en cours...' ;;
            de) echo 'Installation läuft...' ;;
            es) echo 'Instalando...' ;;
            it) echo 'Installazione in corso...' ;;
            ar) echo 'جاري التثبيت...' ;;
            ru) echo 'Установка...' ;;
        esac
        ;;
    backup_config)
        case "$LANG_CHOICE" in
            zh) echo '已备份用户配置' ;;
            en) echo 'User config backed up' ;;
            ja) echo 'ユーザー設定をバックアップしました' ;;
            ko) echo '사용자 설정 백업 완료' ;;
            fr) echo 'Configuration utilisateur sauvegardée' ;;
            de) echo 'Benutzerkonfiguration gesichert' ;;
            es) echo 'Configuración de usuario respaldada' ;;
            it) echo 'Configurazione utente salvata' ;;
            ar) echo 'تم نسخ إعدادات المستخدم احتياطياً' ;;
            ru) echo 'Настройки пользователя сохранены' ;;
        esac
        ;;
    extract_fail)
        case "$LANG_CHOICE" in
            zh) echo '解压失败' ;;
            en) echo 'Extraction failed' ;;
            ja) echo '展開失敗' ;;
            ko) echo '압축 해제 실패' ;;
            fr) echo 'Échec de l'\''extraction' ;;
            de) echo 'Entpacken fehlgeschlagen' ;;
            es) echo 'Error de extracción' ;;
            it) echo 'Estrazione fallita' ;;
            ar) echo 'فشل فك الضغط' ;;
            ru) echo 'Ошибка распаковки' ;;
        esac
        ;;
    config_restored)
        case "$LANG_CHOICE" in
            zh) echo '配置已恢复（API Key 已保留，密码已重置）' ;;
            en) echo 'Config restored (API Keys preserved, password reset)' ;;
            ja) echo '設定を復元しました（APIキー保持、パスワードリセット）' ;;
            ko) echo '설정 복원됨 (API 키 보존, 비밀번호 초기화)' ;;
            fr) echo 'Configuration restaurée (clés API conservées, mot de passe réinitialisé)' ;;
            de) echo 'Konfiguration wiederhergestellt (API-Keys erhalten, Passwort zurückgesetzt)' ;;
            es) echo 'Configuración restaurada (claves API conservadas, contraseña restablecida)' ;;
            it) echo 'Configurazione ripristinata (API Key conservate, password reimpostata)' ;;
            ar) echo 'تمت استعادة الإعدادات (مفاتيح API محفوظة، تم إعادة تعيين كلمة المرور)' ;;
            ru) echo 'Настройки восстановлены (ключи API сохранены, пароль сброшен)' ;;
        esac
        ;;
    no_python_found)
        case "$LANG_CHOICE" in
            zh) echo '未找到 Python >= 3.8，请先安装 Python' ;;
            en) echo 'Python >= 3.8 not found, install Python first' ;;
            ja) echo 'Python 3.8 以上が見つかりません。先にPythonをインストールしてください' ;;
            ko) echo 'Python 3.8 이상을 찾을 수 없습니다. Python을 먼저 설치하세요' ;;
            fr) echo 'Python >= 3.8 introuvable, installez Python d'\''abord' ;;
            de) echo 'Python >= 3.8 nicht gefunden, zuerst Python installieren' ;;
            es) echo 'Python >= 3.8 no encontrado, instale Python primero' ;;
            it) echo 'Python >= 3.8 non trovato, installa prima Python' ;;
            ar) echo 'لم يتم العثور على Python >= 3.8، ثبّت Python أولاً' ;;
            ru) echo 'Python >= 3.8 не найден, установите Python' ;;
        esac
        ;;
    using_python)
        case "$LANG_CHOICE" in
            zh) echo '使用 Python' ;;
            en) echo 'Using Python' ;;
            ja) echo 'Python を使用' ;;
            ko) echo 'Python 사용' ;;
            fr) echo 'Utilisation de Python' ;;
            de) echo 'Python wird verwendet' ;;
            es) echo 'Usando Python' ;;
            it) echo 'Utilizzo di Python' ;;
            ar) echo 'استخدام Python' ;;
            ru) echo 'Использование Python' ;;
        esac
        ;;
    venv_fail)
        case "$LANG_CHOICE" in
            zh) echo '创建虚拟环境失败' ;;
            en) echo 'Failed to create venv' ;;
            ja) echo '仮想環境の作成に失敗しました' ;;
            ko) echo '가상 환경 생성 실패' ;;
            fr) echo 'Échec de la création de l'\''environnement virtuel' ;;
            de) echo 'Venv-Erstellung fehlgeschlagen' ;;
            es) echo 'Error al crear el entorno virtual' ;;
            it) echo 'Creazione dell'\''ambiente virtuale fallita' ;;
            ar) echo 'فشل إنشاء البيئة الافتراضية' ;;
            ru) echo 'Ошибка создания виртуального окружения' ;;
        esac
        ;;
    dep_fail)
        case "$LANG_CHOICE" in
            zh) echo '依赖安装失败' ;;
            en) echo 'Dependency install failed' ;;
            ja) echo '依存関係のインストールに失敗しました' ;;
            ko) echo '의존성 설치 실패' ;;
            fr) echo 'Échec de l'\''installation des dépendances' ;;
            de) echo 'Abhängigkeitsinstallation fehlgeschlagen' ;;
            es) echo 'Error al instalar dependencias' ;;
            it) echo 'Installazione delle dipendenze fallita' ;;
            ar) echo 'فشل تثبيت التبعيات' ;;
            ru) echo 'Ошибка установки зависимостей' ;;
        esac
        ;;
    install_done)
        case "$LANG_CHOICE" in
            zh) echo '安装完成' ;;
            en) echo 'Installation complete' ;;
            ja) echo 'インストール完了' ;;
            ko) echo '설치 완료' ;;
            fr) echo 'Installation terminée' ;;
            de) echo 'Installation abgeschlossen' ;;
            es) echo 'Instalación completa' ;;
            it) echo 'Installazione completata' ;;
            ar) echo 'اكتمل التثبيت' ;;
            ru) echo 'Установка завершена' ;;
        esac
        ;;
    step_verify)
        case "$LANG_CHOICE" in
            zh) echo '验证安装...' ;;
            en) echo 'Verifying installation...' ;;
            ja) echo 'インストールを検証中...' ;;
            ko) echo '설치 확인 중...' ;;
            fr) echo 'Vérification de l'\''installation...' ;;
            de) echo 'Installation wird überprüft...' ;;
            es) echo 'Verificando instalación...' ;;
            it) echo 'Verifica dell'\''installazione in corso...' ;;
            ar) echo 'التحقق من التثبيت...' ;;
            ru) echo 'Проверка установки...' ;;
        esac
        ;;
    version_ok)
        case "$LANG_CHOICE" in
            zh) echo "版本 ${INSTALLED_VER} 验证通过" ;;
            en) echo "Version ${INSTALLED_VER} verified" ;;
            ja) echo "バージョン ${INSTALLED_VER} 検証済み" ;;
            ko) echo "버전 ${INSTALLED_VER} 확인됨" ;;
            fr) echo "Version ${INSTALLED_VER} vérifiée" ;;
            de) echo "Version ${INSTALLED_VER} verifiziert" ;;
            es) echo "Versión ${INSTALLED_VER} verificada" ;;
            it) echo "Versione ${INSTALLED_VER} verificata" ;;
            ar) echo "تم التحقق من الإصدار ${INSTALLED_VER}" ;;
            ru) echo "Версия ${INSTALLED_VER} подтверждена" ;;
        esac
        ;;
    version_warn)
        case "$LANG_CHOICE" in
            zh) echo "版本 ${INSTALLED_VER}（期望 ${VERSION}）" ;;
            en) echo "Version ${INSTALLED_VER} (expected ${VERSION})" ;;
            ja) echo "バージョン ${INSTALLED_VER}（期待値 ${VERSION}）" ;;
            ko) echo "버전 ${INSTALLED_VER} (예상 ${VERSION})" ;;
            fr) echo "Version ${INSTALLED_VER} (attendu ${VERSION})" ;;
            de) echo "Version ${INSTALLED_VER} (erwartet ${VERSION})" ;;
            es) echo "Versión ${INSTALLED_VER} (esperada ${VERSION})" ;;
            it) echo "Versione ${INSTALLED_VER} (attesa ${VERSION})" ;;
            ar) echo "الإصدار ${INSTALLED_VER} (المتوقع ${VERSION})" ;;
            ru) echo "Версия ${INSTALLED_VER} (ожидается ${VERSION})" ;;
        esac
        ;;
    install_banner)
        case "$LANG_CHOICE" in
            zh) echo 'meshctx 安装完成！ 🎉' ;;
            en) echo 'meshctx Installed! 🎉' ;;
            ja) echo 'meshctx インストール完了！ 🎉' ;;
            ko) echo 'meshctx 설치 완료! 🎉' ;;
            fr) echo 'meshctx installé ! 🎉' ;;
            de) echo 'meshctx installiert! 🎉' ;;
            es) echo '¡meshctx instalado! 🎉' ;;
            it) echo 'meshctx installato! 🎉' ;;
            ar) echo 'تم تثبيت meshctx! 🎉' ;;
            ru) echo 'meshctx установлен! 🎉' ;;
        esac
        ;;
    quick_start)
        case "$LANG_CHOICE" in
            zh) echo '快速开始' ;;
            en) echo 'Quick Start' ;;
            ja) echo 'クイックスタート' ;;
            ko) echo '빠른 시작' ;;
            fr) echo 'Démarrage rapide' ;;
            de) echo 'Schnellstart' ;;
            es) echo 'Inicio rápido' ;;
            it) echo 'Avvio rapido' ;;
            ar) echo 'بداية سريعة' ;;
            ru) echo 'Быстрый старт' ;;
        esac
        ;;
    cmd_start)
        case "$LANG_CHOICE" in
            zh) echo '启动服务' ;;
            en) echo 'Start service' ;;
            ja) echo 'サービス起動' ;;
            ko) echo '서비스 시작' ;;
            fr) echo 'Démarrer le service' ;;
            de) echo 'Dienst starten' ;;
            es) echo 'Iniciar servicio' ;;
            it) echo 'Avvia servizio' ;;
            ar) echo 'بدء الخدمة' ;;
            ru) echo 'Запуск службы' ;;
        esac
        ;;
    open_browser)
        case "$LANG_CHOICE" in
            zh) echo "浏览器打开 http://localhost:${PORT}/ui/setup" ;;
            en) echo "Open http://localhost:${PORT}/ui/setup" ;;
            ja) echo "ブラウザで http://localhost:${PORT}/ui/setup を開く" ;;
            ko) echo "브라우저에서 http://localhost:${PORT}/ui/setup 열기" ;;
            fr) echo "Ouvrir http://localhost:${PORT}/ui/setup" ;;
            de) echo "http://localhost:${PORT}/ui/setup öffnen" ;;
            es) echo "Abrir http://localhost:${PORT}/ui/setup" ;;
            it) echo "Apri http://localhost:${PORT}/ui/setup" ;;
            ar) echo "افتح http://localhost:${PORT}/ui/setup" ;;
            ru) echo "Откройте http://localhost:${PORT}/ui/setup" ;;
        esac
        ;;
    setup_api)
        case "$LANG_CHOICE" in
            zh) echo '在 Setup 页面配置 API Key' ;;
            en) echo 'Configure API Key on Setup page' ;;
            ja) echo 'Setup ページで API キーを設定' ;;
            ko) echo 'Setup 페이지에서 API 키 구성' ;;
            fr) echo 'Configurez la clé API sur la page Setup' ;;
            de) echo 'API-Key auf der Setup-Seite konfigurieren' ;;
            es) echo 'Configure la clave API en la página Setup' ;;
            it) echo 'Configura la chiave API nella pagina Setup' ;;
            ar) echo 'اضبط مفتاح API في صفحة الإعداد' ;;
            ru) echo 'Настройте API-ключ на странице настроек' ;;
        esac
        ;;
    open_dashboard)
        case "$LANG_CHOICE" in
            zh) echo '打开 Dashboard 查看状态' ;;
            en) echo 'Open Dashboard to view status' ;;
            ja) echo 'Dashboard を開いて状態を確認' ;;
            ko) echo 'Dashboard 열어 상태 확인' ;;
            fr) echo 'Ouvrez le tableau de bord pour voir l'\''état' ;;
            de) echo 'Dashboard öffnen um Status anzuzeigen' ;;
            es) echo 'Abra el panel para ver el estado' ;;
            it) echo 'Apri la Dashboard per vedere lo stato' ;;
            ar) echo 'افتح لوحة التحكم لعرض الحالة' ;;
            ru) echo 'Откройте панель управления для просмотра статуса' ;;
        esac
        ;;
    tip_refresh)
        case "$LANG_CHOICE" in
            zh) echo '首次访问：按 Ctrl+Shift+R 强制刷新浏览器缓存' ;;
            en) echo 'First visit: press Ctrl+Shift+R to force-refresh browser cache' ;;
            ja) echo '初回アクセス: Ctrl+Shift+R でブラウザキャッシュを強制リフレッシュ' ;;
            ko) echo '첫 방문: Ctrl+Shift+R로 브라우저 캐시 강제 새로고침' ;;
            fr) echo 'Première visite : Ctrl+Shift+R pour vider le cache du navigateur' ;;
            de) echo 'Erster Besuch: Strg+Shift+R zum Leeren des Browser-Caches' ;;
            es) echo 'Primera visita: Ctrl+Shift+R para forzar actualización de caché' ;;
            it) echo 'Prima visita: premi Ctrl+Shift+R per forzare l'\''aggiornamento della cache' ;;
            ar) echo 'أول زيارة: اضغط Ctrl+Shift+R لتحديث ذاكرة التخزين المؤقت' ;;
            ru) echo 'При первом визите: Ctrl+Shift+R для обновления кэша' ;;
        esac
        ;;
    common_cmds)
        case "$LANG_CHOICE" in
            zh) echo '常用命令' ;;
            en) echo 'Common Commands' ;;
            ja) echo 'よく使うコマンド' ;;
            ko) echo '자주 쓰는 명령어' ;;
            fr) echo 'Commandes courantes' ;;
            de) echo 'Häufige Befehle' ;;
            es) echo 'Comandos comunes' ;;
            it) echo 'Comandi comuni' ;;
            ar) echo 'أوامر شائعة' ;;
            ru) echo 'Частые команды' ;;
        esac
        ;;
    tip_abnormal)
        case "$LANG_CHOICE" in
            zh) echo '如果页面显示异常，请按 Ctrl+Shift+R 强制刷新浏览器缓存' ;;
            en) echo 'If page looks broken, press Ctrl+Shift+R to force-refresh browser cache' ;;
            ja) echo 'ページが崩れている場合は Ctrl+Shift+R でブラウザキャッシュを強制リフレッシュ' ;;
            ko) echo '페이지가 깨져 보이면 Ctrl+Shift+R로 브라우저 캐시 강제 새로고침' ;;
            fr) echo 'Si la page semble cassée, faites Ctrl+Shift+R pour vider le cache' ;;
            de) echo 'Falls die Seite defekt aussieht: Strg+Shift+R zum Leeren des Browser-Caches' ;;
            es) echo 'Si la página se ve mal, presione Ctrl+Shift+R para forzar actualización' ;;
            it) echo 'Se la pagina appare rotta, premi Ctrl+Shift+R per forzare l'\''aggiornamento della cache' ;;
            ar) echo 'إذا بدت الصفحة معطلة، اضغط Ctrl+Shift+R لتحديث ذاكرة التخزين المؤقت' ;;
            ru) echo 'Если страница не работает, нажмите Ctrl+Shift+R' ;;
        esac
        ;;
    run_now)
        case "$LANG_CHOICE" in
            zh) echo '立即运行' ;;
            en) echo 'Run now' ;;
            ja) echo '今すぐ実行' ;;
            ko) echo '지금 실행' ;;
            fr) echo 'Exécuter maintenant' ;;
            de) echo 'Jetzt ausführen' ;;
            es) echo 'Ejecutar ahora' ;;
            it) echo 'Esegui ora' ;;
            ar) echo 'شغّل الآن' ;;
            ru) echo 'Запустить сейчас' ;;
        esac
        ;;
    cmd_path_ok)
        case "$LANG_CHOICE" in
            zh) echo 'meshctx 命令已添加到 PATH（无需 sudo）' ;;
            en) echo 'meshctx command added to PATH (no sudo)' ;;
            ja) echo 'meshctx コマンドを PATH に追加しました（sudo不要）' ;;
            ko) echo 'meshctx 명령이 PATH에 추가됨 (sudo 불필요)' ;;
            fr) echo 'Commande meshctx ajoutée au PATH (sans sudo)' ;;
            de) echo 'meshctx-Befehl zum PATH hinzugefügt (kein sudo)' ;;
            es) echo 'Comando meshctx añadido al PATH (sin sudo)' ;;
            it) echo 'Comando meshctx aggiunto al PATH (senza sudo)' ;;
            ar) echo 'تمت إضافة أمر meshctx إلى PATH (بدون sudo)' ;;
            ru) echo 'Команда meshctx добавлена в PATH (без sudo)' ;;
        esac
        ;;
    new_terminal)
        case "$LANG_CHOICE" in
            zh) echo '新终端执行: source $SHELL_RC    # 或重新打开终端' ;;
            en) echo 'New terminal: source $SHELL_RC    # or reopen terminal' ;;
            ja) echo '新しい端末: source $SHELL_RC    # または端末を再起動' ;;
            ko) echo '새 터미널: source $SHELL_RC    # 또는 터미널 재시작' ;;
            fr) echo 'Nouveau terminal : source $SHELL_RC    # ou rouvrez le terminal' ;;
            de) echo 'Neues Terminal: source $SHELL_RC    # oder Terminal neu öffnen' ;;
            es) echo 'Nuevo terminal: source $SHELL_RC    # o reabra el terminal' ;;
            it) echo 'Nuovo terminale: source $SHELL_RC    # o riapri il terminale' ;;
            ar) echo 'طرفية جديدة: source $SHELL_RC    # أو أعد فتح الطرفية' ;;
            ru) echo 'Новый терминал: source $SHELL_RC    # или переоткройте терминал' ;;
        esac
        ;;
    auto_stopped)
        case "$LANG_CHOICE" in
            zh) echo '旧进程已自动停止，无冲突' ;;
            en) echo 'Old process auto-stopped, no conflicts' ;;
            ja) echo '古いプロセスを自動停止しました。競合なし' ;;
            ko) echo '이전 프로세스 자동 중지, 충돌 없음' ;;
            fr) echo 'Ancien processus arrêté automatiquement, aucun conflit' ;;
            de) echo 'Alter Prozess automatisch beendet, keine Konflikte' ;;
            es) echo 'Proceso antiguo detenido automáticamente, sin conflictos' ;;
            it) echo 'Vecchio processo arrestato automaticamente, nessun conflitto' ;;
            ar) echo 'تم إيقاف العملية القديمة تلقائياً، لا يوجد تعارض' ;;
            ru) echo 'Старый процесс остановлен автоматически, конфликтов нет' ;;
        esac
        ;;
    *) echo "$1" ;;
    esac
}

INSTALL_DIR="${HOME}/.meshctx"
VERSION="3.123.0"
REPO="LucyAndLuna2023/meshctx"
SRC_URL="https://github.com/${REPO}/archive/refs/tags/v${VERSION}.tar.gz"
PORT=3001

echo ""
echo -e "  ${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "  ${CYAN}  ║     $(T header_installer)              ║${NC}"
echo -e "  ${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 停止旧版本 ──────────────────────────────────────
echo -e "${CYAN}[1/5]${NC} $(T step_stop)"
KILLED=0
# 停止本机 uvicorn
if pgrep -f "uvicorn.*src.main" >/dev/null 2>&1; then
    pkill -9 -f "uvicorn.*src.main" 2>/dev/null || true
    KILLED=1
fi
# 停止 meshctx 产品 CLI 进程（仅精确匹配 src.cli，禁止用 "python.*meshctx" 这种会误杀 hermes -p meshctx 的宽模式）
if pgrep -f "python3? -m src\.cli" >/dev/null 2>&1; then
    pkill -9 -f "python3? -m src\.cli" 2>/dev/null || true
    KILLED=1
fi
# 停止 PyInstaller 封装版进程（护城河 2026-08-23 起默认完整版封装）
if pgrep -f "meshctx-linux/meshctx" >/dev/null 2>&1; then
    pkill -9 -f "meshctx-linux/meshctx" 2>/dev/null || true
    KILLED=1
fi
sleep 1

# 释放端口
if command -v ss >/dev/null 2>&1; then
    PORT_PID=$(ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | head -1)
elif command -v lsof >/dev/null 2>&1; then
    PORT_PID=$(lsof -ti:${PORT} 2>/dev/null | head -1)
else
    PORT_PID=""
fi
if [ -n "$PORT_PID" ]; then
    # 2026-08-25 004meshctx 审计修复: 仅杀 meshctx 相关进程, 禁止 kill -9 任意占用者 (误杀风险)
    # 通过 /proc/<pid>/cmdline 校验进程归属
    _CMD=""
    if [ -r "/proc/${PORT_PID}/cmdline" ]; then
        _CMD=$(tr '\0' ' ' < "/proc/${PORT_PID}/cmdline" 2>/dev/null)
    fi
    case "$_CMD" in
        *meshctx*|*src.main*|*src.cli*|*uvicorn*)
            kill -9 "$PORT_PID" 2>/dev/null || true
            KILLED=1
            ;;
        *)
            echo -e "  ${YELLOW}⚠${NC} 端口 ${PORT} 被非 meshctx 进程占用 (PID=${PORT_PID}): $_CMD"
            echo -e "  ${YELLOW}⚠${NC} 已跳过 (不误杀)。请手动停止该进程后重试。"
            ;;
    esac
fi

if [ "$KILLED" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} $(T stopped_ok)"
else
    echo -e "  ${GREEN}✓${NC} $(T no_stop_needed)"
fi

# ── Check Python ──────────────────────────────────────
echo -e "${CYAN}[2/5]${NC} $(T step_check)"
python3 --version >/dev/null 2>&1 || {
    echo -e "${RED}✗ $(T need_python)"
    exit 1
}
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null && echo 1 || echo 0)
if [ "$PY_OK" = "0" ]; then
    echo -e "${RED}✗ $(T need_python_ver)"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python ${PY_VER}"

# ── Download ────────────────────────────────────────────
echo -e "${CYAN}[3/5]${NC} $(T step_download) ${VERSION}..."
TMPDIR=$(mktemp -d)
TARBALL="${TMPDIR}/meshctx-src.tar.gz"
PORTABLE_TARBALL="${TMPDIR}/meshctx-linux.tar.gz"
PORTABLE_URL="${MESHCTX_PORTABLE_URL:-https://github.com/${REPO}/releases/download/v${VERSION}/meshctx-linux.tar.gz}"
PORTABLE_OK=0
trap "rm -rf ${TMPDIR}" EXIT

# 护城河(2026-08-23): 默认下载 PyInstaller 封装资产 meshctx-linux.tar.gz —
# 闭源核心已编译进包(无明文源码), 一次装好完整产品; 资产不可用(旧版本/网络)时回退源码包+token 安装
# github.com 主站在国内常不可达 → 直连失败后依次尝试公共加速镜像（仅对 github.com 官方 URL 生效，不含 token）
GIT_MIRRORS="https://ghfast.top/ https://gh-proxy.com/ https://ghproxy.net/"

_fetch_url() {
    _url="$1"; _out="$2"
    _dl() {
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL --connect-timeout 30 --max-time 900 --retry 1 -o "${_out}" "${1}" 2>/dev/null
        elif command -v wget >/dev/null 2>&1; then
            wget -q --timeout=120 --tries=2 -O "${_out}" "${1}" 2>/dev/null
        else
            return 1
        fi
    }
    # 下载 + tarball 完整性校验（ghproxy.net 等镜像可能截断，损坏包换下一镜像）
    _dl_ok() {
        _dl "$1" && tar tzf "${_out}" >/dev/null 2>&1
    }
    if _dl_ok "${_url}"; then return 0; fi
    case "${_url}" in
        https://github.com/*)
            for _m in ${GIT_MIRRORS}; do
                echo -e "  ${YELLOW}→${NC} Direct download failed or incomplete, trying mirror ${_m} ..."
                if _dl_ok "${_m}${_url}"; then return 0; fi
            done
            ;;
    esac
    return 1
}

DOWNLOAD_OK=0
if [ -z "$MESHCTX_SRC_TARBALL" ]; then
    _fetch_url "${PORTABLE_URL}" "${PORTABLE_TARBALL}" && PORTABLE_OK=1
fi
if [ "$PORTABLE_OK" = "1" ]; then
    # 封装资产校验: 必须含 meshctx-linux/meshctx 可执行 (PyInstaller onedir 结构)
    if tar tzf "${PORTABLE_TARBALL}" 2>/dev/null | grep -q "meshctx-linux/meshctx$"; then
        TARBALL="${PORTABLE_TARBALL}"
        echo -e "  ${GREEN}✓${NC} $(T download_ok) full portable build ($(du -h "${TARBALL}" | cut -f1))"
    else
        PORTABLE_OK=0
        echo -e "  ${YELLOW}⚠${NC} Portable build structure abnormal, falling back to source package..."
    fi
fi
if [ "$PORTABLE_OK" != "1" ]; then
    # 支持本地预置源码包（离线/受限网络环境：GitHub 不可直连时）
    if [ -n "$MESHCTX_SRC_TARBALL" ] && [ -f "$MESHCTX_SRC_TARBALL" ]; then
        cp "$MESHCTX_SRC_TARBALL" "$TARBALL" && DOWNLOAD_OK=1
    else
        _fetch_url "${SRC_URL}" "${TARBALL}" && DOWNLOAD_OK=1
    fi
    if [ "$DOWNLOAD_OK" != "1" ]; then
        echo -e "${RED}✗ $(T download_fail)${NC}"
        echo "  $(T download_fail_hint)"
        echo "  ${PORTABLE_URL}"
        echo "  ${SRC_URL}"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} $(T download_ok) ($(du -h "${TARBALL}" | cut -f1))"
fi
PORTABLE_MODE="$PORTABLE_OK"

# ── Backup user config ────────────────────────────────────
echo -e "${CYAN}[4/6]${NC} $(T step_install)"
CONFIG_BACKUP=""
if [ -d "${INSTALL_DIR}" ]; then
    # 备份用户的重要配置文件（Key、模型配置等）
    CONFIG_BACKUP=$(mktemp -d)
    for f in config.yaml .env provider_config.json; do
        if [ -f "${INSTALL_DIR}/${f}" ]; then
            cp "${INSTALL_DIR}/${f}" "${CONFIG_BACKUP}/${f}" 2>/dev/null || true
        fi
    done
    # 备份 CLI 历史输入记录（.history_*）与非 default profile 数据（profiles/）与激活 profile 标记
    for h in "${INSTALL_DIR}"/.history_*; do
        [ -e "$h" ] && cp -a "$h" "${CONFIG_BACKUP}/" 2>/dev/null || true
    done
    if [ -d "${INSTALL_DIR}/profiles" ]; then
        cp -a "${INSTALL_DIR}/profiles" "${CONFIG_BACKUP}/" 2>/dev/null || true
    fi
    [ -f "${INSTALL_DIR}/.active_profile" ] && cp "${INSTALL_DIR}/.active_profile" "${CONFIG_BACKUP}/" 2>/dev/null || true
    # 2026-08-25 004meshctx 审计修复 (P1): 重装不得丢失用户数据 — 备份全部数据目录
    # data/ 含 projects/agents/conversations 持久化; 其余为记忆/会话/知识库等运行数据
    for d in data conversations agents knowledge memories goals genomes heartbeats backups diff_backups crew_templates archives; do
        if [ -d "${INSTALL_DIR}/${d}" ]; then
            cp -a "${INSTALL_DIR}/${d}" "${CONFIG_BACKUP}/" 2>/dev/null || true
        fi
    done
    # 也备份项目根目录的 provider_config.json（如果在别处）
    [ -z "$CONFIG_BACKUP" ] || echo -e "  ${GREEN}✓${NC} $(T backup_config)"
fi

rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
if [ "$PORTABLE_MODE" = "1" ]; then
    tar xzf "${TARBALL}" -C "${INSTALL_DIR}" || {
        echo -e "${RED}✗ $(T extract_fail)${NC}"; exit 1
    }
    if [ ! -x "${INSTALL_DIR}/meshctx-linux/meshctx" ]; then
        echo -e "${RED}✗ Portable build missing meshctx executable${NC}"; exit 1
    fi
    # 护城河校验: 封装资产必须含闭源核心（缺核心 = stub, 不得安装为"完整版"）
    VHOME=$(mktemp -d)
    if ! _PROBE=$(HOME="$VHOME" "${INSTALL_DIR}/meshctx-linux/meshctx" model add deepseek:v4-flash --key sk-gate-verify 2>&1); then
        echo -e "${RED}✗ Portable build probe failed (binary cannot run / missing libraries?)${NC}"
        echo "$_PROBE" | tail -5
        rm -rf "$VHOME"
        exit 1
    fi
    rm -rf "$VHOME"
    if echo "$_PROBE" | grep -q "STUB mode"; then
        echo -e "${RED}✗ Portable build missing closed-source core (stub) — full product must include the core, use a new release asset with the core${NC}"
        echo "$_PROBE" | tail -5
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Portable build includes closed-source core (full build)"
else
    tar xzf "${TARBALL}" -C "${INSTALL_DIR}" || {
        echo -e "${RED}✗ $(T extract_fail)${NC}"; exit 1
    }
    # 处理 tag 归档顶层目录 (meshctx-<branch>/)，把源码拍平到 INSTALL_DIR
    _SUBDIR=$(find "${INSTALL_DIR}" -maxdepth 1 -mindepth 1 -type d | head -1)
    if [ -n "$_SUBDIR" ] && [ -f "${_SUBDIR}/src/main.py" ]; then
        mv "${_SUBDIR}"/* "${_SUBDIR}"/.[!.]* "${INSTALL_DIR}"/ 2>/dev/null || true
        rmdir "${_SUBDIR}" 2>/dev/null || true
    fi
fi

# ── Restore user config ────────────────────────────────────
if [ -n "$CONFIG_BACKUP" ] && [ -d "$CONFIG_BACKUP" ]; then
    RESTORED=0
    for f in config.yaml .env; do
        if [ -f "${CONFIG_BACKUP}/${f}" ]; then
            cp "${CONFIG_BACKUP}/${f}" "${INSTALL_DIR}/${f}" 2>/dev/null || true
            RESTORED=1
        fi
    done
    # provider_config.json 位于项目根目录
    if [ -f "${CONFIG_BACKUP}/provider_config.json" ]; then
        cp "${CONFIG_BACKUP}/provider_config.json" "${INSTALL_DIR}/provider_config.json" 2>/dev/null || true
        RESTORED=1
    fi
    # CLI 历史 / profiles / 激活标记 一并恢复（与备份对应，重装不得丢失组件）
    for h in "${CONFIG_BACKUP}"/.history_*; do
        [ -e "$h" ] && cp -a "$h" "${INSTALL_DIR}/" 2>/dev/null || true
    done
    if [ -d "${CONFIG_BACKUP}/profiles" ]; then
        cp -a "${CONFIG_BACKUP}/profiles" "${INSTALL_DIR}/" 2>/dev/null || true
    fi
    [ -f "${CONFIG_BACKUP}/.active_profile" ] && cp "${CONFIG_BACKUP}/.active_profile" "${INSTALL_DIR}/" 2>/dev/null || true
    # 2026-08-25 004meshctx 审计修复 (P1): 恢复全部用户数据目录 (与备份对应)
    for d in data conversations agents knowledge memories goals genomes heartbeats backups diff_backups crew_templates archives; do
        if [ -d "${CONFIG_BACKUP}/${d}" ]; then
            cp -a "${CONFIG_BACKUP}/${d}" "${INSTALL_DIR}/" 2>/dev/null || true
            RESTORED=1
        fi
    done
    # 🔒 安全: 永远不恢复旧密码，新安装默认无需密码
    if [ -f "${INSTALL_DIR}/.env" ]; then
        sed -i '/^MESHCTX_PASSWORD=/d' "${INSTALL_DIR}/.env" 2>/dev/null || true
    fi
    rm -rf "$CONFIG_BACKUP"
    [ "$RESTORED" = "0" ] || echo -e "  ${GREEN}✓${NC} $(T config_restored)"
fi

cd "${INSTALL_DIR}"

if [ "$PORTABLE_MODE" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} $(T install_done) (PyInstaller portable build, no Python dependency install needed)"
else
# venv — robust creation with multiple fallbacks
PYTHON_BIN=""
for p in python3 python3.11 python3.12 python3.10 python; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$($p --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ] 2>/dev/null; then
            PYTHON_BIN="$p"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}✗ $(T no_python_found)${NC}"
    echo -e "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo -e "  CentOS/RHEL:   sudo yum install python3 python3-pip"
    echo -e "  macOS:         brew install python@3.12"
    exit 1
fi

echo -e "  ${CYAN}→${NC} $(T using_python): $PYTHON_BIN ($($PYTHON_BIN --version))"

if [ ! -d "venv" ]; then
    # Try standard venv first
    $PYTHON_BIN -m venv venv 2>/dev/null || {
        # Fallback: ensurepip + venv
        $PYTHON_BIN -m ensurepip --upgrade 2>/dev/null || true
        $PYTHON_BIN -m venv venv --without-pip 2>/dev/null && {
            source venv/bin/activate
            curl -sS https://bootstrap.pypa.io/get-pip.py | $PYTHON_BIN 2>/dev/null || true
        } || {
            # Last resort: virtualenv
            pip install virtualenv 2>/dev/null || $PYTHON_BIN -m pip install virtualenv 2>/dev/null
            $PYTHON_BIN -m virtualenv venv 2>/dev/null || {
                echo -e "${RED}✗ $(T venv_fail)${NC}"
                echo -e "  Ubuntu/Debian: sudo apt install python3-venv python3-pip"
                echo -e "  CentOS/RHEL:   sudo yum install python3-pip && pip3 install virtualenv"
                echo -e "  Arch:          sudo pacman -S python-virtualenv"
                exit 1
            }
        }
    }
fi
source venv/bin/activate

# 依赖
pip install -q --upgrade pip 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null || {
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart playwright 2>/dev/null || {
        echo -e "${RED}✗ $(T dep_fail)${NC}"; exit 1
    }
}

# Playwright 浏览器内核 (meshctx browser 子命令需要, 001geo审计建议 2026-08-16)
pip install -q playwright 2>/dev/null || true
$PYTHON_BIN -m playwright install chromium --with-deps 2>/dev/null || $PYTHON_BIN -m playwright install chromium 2>/dev/null || true

fi

# meshctx 命令
mkdir -p ~/bin
if [ "$PORTABLE_MODE" = "1" ]; then
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
exec ~/.meshctx/meshctx-linux/meshctx "$@"
SCRIPT
else
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
cd ~/.meshctx && source venv/bin/activate && python -m src.cli "$@"
SCRIPT
fi
chmod +x ~/bin/meshctx

# PATH — 支持 bash/zsh/fish
SHELL_RC=""
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile"; do
    if [ -f "$rc" ] || [ "$SHELL" = "/bin/zsh" -a "$rc" = "$HOME/.zshrc" ]; then
        SHELL_RC="$rc"
        break
    fi
done
[ -z "$SHELL_RC" ] && SHELL_RC="$HOME/.bashrc"

if ! echo "$PATH" | grep -q "$HOME/bin"; then
    echo "export PATH=\"\$HOME/bin:\$PATH\"" >> "$SHELL_RC"
fi
export PATH="$HOME/bin:$PATH"

# 系统级 symlink — 不强制 sudo，优先用 ~/.local/bin（用户可写）
SYMLINK_OK=0
for _dir in "$HOME/.local/bin" "$HOME/bin"; do
    if [ -d "$_dir" ] && [ -w "$_dir" ]; then
        ln -sf "$HOME/bin/meshctx" "$_dir/meshctx" 2>/dev/null && SYMLINK_OK=1 && break
    fi
done
# 兜底：/usr/local/bin 可写则写，否则跳过（不再弹 sudo）
if [ "$SYMLINK_OK" = "0" ]; then
    if [ -w /usr/local/bin ]; then
        ln -sf "$HOME/bin/meshctx" /usr/local/bin/meshctx 2>/dev/null && SYMLINK_OK=1
    fi
fi

echo -e "  ${GREEN}✓${NC} $(T install_done)"

# ── Verify ────────────────────────────────────────────
echo -e "${CYAN}[5/6]${NC} $(T step_verify)"
if [ "$PORTABLE_MODE" = "1" ]; then
    if [ -x "${INSTALL_DIR}/meshctx-linux/meshctx" ]; then
        echo -e "  ${GREEN}✓${NC} $(T version_ok) (full portable build, closed-source core embedded)"
    else
        echo -e "  ${YELLOW}⚠${NC} $(T version_warn)"
    fi
else
    source venv/bin/activate
    INSTALLED_VER=$(python -c "from src.core import __version__; print(__version__)" 2>/dev/null || echo "?")
    if [ "$INSTALLED_VER" = "$VERSION" ]; then
        echo -e "  ${GREEN}✓${NC} $(T version_ok)"
    else
        echo -e "  ${YELLOW}⚠${NC} $(T version_warn)"
    fi
fi

# ── 闭源核心组件 (meshctx-core · 一体产品) ─────────────────
# 开源 + 闭源是一个整体产品：提供 MESHCTX_CORE_TOKEN 则一并安装闭源核心
# （从私有仓库 LucyAndLuna2023/meshctx-core 拉取真实核心算法模块），
# 未提供 token 则保留开源 stub 降级，之后可随时重跑补装。
if [ "$PORTABLE_MODE" = "1" ]; then
    echo -e "  ${CYAN}[6/6]${NC} Full portable build already includes closed-source core, no extra install needed"
else
CORE_TOKEN="${MESHCTX_CORE_TOKEN:-}"
if [ -z "$CORE_TOKEN" ] && [ -f "${INSTALL_DIR}/.env" ]; then
    CORE_TOKEN=$(sed -n 's/^MESHCTX_CORE_TOKEN=//p' "${INSTALL_DIR}/.env" 2>/dev/null | tr -d '"'"'"'\r')
fi
if [ -n "$CORE_TOKEN" ] && command -v git >/dev/null 2>&1; then
    echo -e "${CYAN}[6/6]${NC} Installing closed-source core meshctx-core ..."
    CORE_TMP=$(mktemp -d)
    CORE_CLONE_OK=0
    git clone --depth 1 "https://${CORE_TOKEN}@github.com/LucyAndLuna2023/meshctx-core.git" "${CORE_TMP}/core" >/dev/null 2>&1 && CORE_CLONE_OK=1
    if [ "$CORE_CLONE_OK" != "1" ] && [ -n "${MESHCTX_GIT_PROXY:-}" ]; then
        git -c http.proxy="$MESHCTX_GIT_PROXY" -c https.proxy="$MESHCTX_GIT_PROXY" clone --depth 1 "https://${CORE_TOKEN}@github.com/LucyAndLuna2023/meshctx-core.git" "${CORE_TMP}/core" >/dev/null 2>&1 && CORE_CLONE_OK=1
    fi
    if [ "$CORE_CLONE_OK" = "1" ]; then
        # 真实核心算法模块递归落地到 src/core（跳过顶层 __init__.py 保留开源 stub 路由,
        # 闭源业务模块覆盖同名 stub + 补入闭源独有模块, 检测逻辑按 desktop_tool.py 落地判定完整版）
        # 与 install-mac.sh 保持一致：递归复制 + 保留子目录结构，未来核心新增子目录模块也不遗漏
        (cd "${CORE_TMP}/core/src/core" && find . -name '*.py' ! -path './__init__.py' | tar -cf - -T -) | (cd "${INSTALL_DIR}/src/core" && tar -xf -)
        echo -e "  ${GREEN}✓${NC} Closed-source core installed as one product (full build)"
    else
        echo -e "${YELLOW}⚠ Closed-source core fetch failed (token/network) — continuing with open-source build (full engine, Open Core). Re-run with MESHCTX_CORE_TOKEN to add the core later${NC}"
    fi
    rm -rf "${CORE_TMP}"
fi
if [ -z "$CORE_TOKEN" ] || ! command -v git >/dev/null 2>&1; then
    echo -e "${CYAN}[6/6]${NC} No MESHCTX_CORE_TOKEN — installing open-source build (full engine, Open Core)."
    echo "    Closed-source core (meshctx-core) is an optional enhancement layer; set MESHCTX_CORE_TOKEN and re-run to add it later."
fi
fi

# ── Done ────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║          $(T install_banner)                     ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
if [ "$KILLED" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} $(T auto_stopped)"
fi
echo -e "  ${CYAN}$(T quick_start):${NC}"
echo "    meshctx start                    # $(T cmd_start)"
echo "    $(T open_browser)"
echo "    → $(T setup_api)"
echo "    → $(T open_dashboard)"
echo ""
echo -e "  ${YELLOW}💡${NC} $(T tip_refresh)"
echo ""
echo -e "  ${CYAN}$(T common_cmds):${NC}"
echo "    meshctx status                   # view status"
echo "    meshctx stop                     # stop service"
echo "    meshctx start --port 8080        # specify port"
echo ""
echo -e "  ${YELLOW}💡${NC} $(T tip_abnormal)"
echo ""
echo -e "  ${GREEN}👉 $(T run_now):${NC}  meshctx start    # $(T cmd_start)"
[ "$SYMLINK_OK" = "1" ] && echo -e "  ${GREEN}✓${NC} $(T cmd_path_ok)"
echo -e "  ${YELLOW}💡${NC} $(T new_terminal)"
echo ""
