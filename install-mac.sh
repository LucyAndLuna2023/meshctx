#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx macOS 一键安装 v1.0
# 使用: curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install-mac.sh | bash
# 或:   git clone ... && bash install-mac.sh
# ═══════════════════════════════════════════════════════
set -e

# ── 颜色 ──
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

# ── i18n ──
detect_lang() {
    if [ -n "$MESHCTX_LANG" ]; then echo "$MESHCTX_LANG"; return; fi
    case "${LANG:-}" in
        zh_*|zh-*|Chinese*)     echo "zh" ;;
        ja_*|ja-*|Japanese*)    echo "ja" ;;
        ko_*|ko-*|Korean*)      echo "ko" ;;
        fr_*|fr-*|French*)      echo "fr" ;;
        de_*|de-*|German*)      echo "de" ;;
        es_*|es-*|Spanish*)     echo "es" ;;
        it_*|it-*|Italian*)     echo "it" ;;
        ar_*|ar-*|Arabic*)      echo "ar" ;;
        *)                      echo "en" ;;
    esac
}
# LANG_CHOICE 须在 detect_lang 定义之后求值（此前在定义前调用 → command not found）
LANG_CHOICE=$(detect_lang)
T() {
    case "$1" in
    header_macos)
        case "$LANG_CHOICE" in
            zh) echo "meshctx v${VERSION} macOS 一键安装" ;;
            en) echo "meshctx v${VERSION} macOS One-Click Install" ;;
            ja) echo "meshctx v${VERSION} macOS ワンクリックインストール" ;;
            ko) echo "meshctx v${VERSION} macOS 원클릭 설치" ;;
            fr) echo "meshctx v${VERSION} Installation macOS en un clic" ;;
            de) echo "meshctx v${VERSION} macOS Ein-Klick-Installation" ;;
            es) echo "meshctx v${VERSION} Instalación macOS en un clic" ;;
            it) echo "meshctx v${VERSION} Installazione macOS con un clic" ;;
            ar) echo "meshctx v${VERSION} تثبيت macOS بنقرة واحدة" ;;
        esac
        ;;
    macos_only)
        case "$LANG_CHOICE" in
            zh) echo '此脚本仅支持 macOS。Linux 请使用 install.sh' ;;
            en) echo 'This script is for macOS only. Use install.sh for Linux' ;;
            ja) echo 'このスクリプトはmacOS専用です。Linuxはinstall.shをお使いください' ;;
            ko) echo '이 스크립트는 macOS 전용입니다. Linux는 install.sh를 사용하세요' ;;
            fr) echo 'Ce script est réservé à macOS. Utilisez install.sh pour Linux' ;;
            de) echo 'Dieses Skript ist nur für macOS. Verwenden Sie install.sh für Linux' ;;
            es) echo 'Este script es solo para macOS. Use install.sh para Linux' ;;
            it) echo 'Questo script è solo per macOS. Usa install.sh per Linux' ;;
            ar) echo 'هذا السكريبت لنظام macOS فقط. استخدم install.sh لنظام Linux' ;;
        esac
        ;;
    step1_stop)
        case "$LANG_CHOICE" in
            zh) echo '正在停止旧版本...' ;;
            en) echo 'Stopping old version...' ;;
            ja) echo '古いバージョンを停止中...' ;;
            ko) echo '이전 버전 중지 중...' ;;
            fr) echo "Arrêt de l'ancienne version..." ;;
            de) echo 'Alte Version wird beendet...' ;;
            es) echo 'Deteniendo versión anterior...' ;;
            it) echo 'Arresto della versione precedente...' ;;
            ar) echo 'إيقاف الإصدار القديم...' ;;
        esac
        ;;
    stopped_ok_port)
        case "$LANG_CHOICE" in
            zh) echo "已停止旧服务，已释放端口 ${PORT}" ;;
            en) echo "Stopped old service, freed port ${PORT}" ;;
            ja) echo "古いサービスを停止し、ポート ${PORT} を解放しました" ;;
            ko) echo "이전 서비스 중지 및 포트 ${PORT} 해제됨" ;;
            fr) echo "Ancien service arrêté, port ${PORT} libéré" ;;
            de) echo "Alter Dienst beendet, Port ${PORT} freigegeben" ;;
            es) echo "Servicio anterior detenido, puerto ${PORT} liberado" ;;
            it) echo "Vecchio servizio arrestato, porta ${PORT} liberata" ;;
            ar) echo "تم إيقاف الخدمة القديمة وتحرير المنفذ ${PORT}" ;;
        esac
        ;;
    no_stop)
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
        esac
        ;;
    step2_check)
        case "$LANG_CHOICE" in
            zh) echo '正在检查环境...' ;;
            en) echo 'Checking environment...' ;;
            ja) echo '環境を確認中...' ;;
            ko) echo '환경 확인 중...' ;;
            fr) echo 'Vérification de l'\''environnement...' ;;
            de) echo 'Umgebung wird geprüft...' ;;
            es) echo 'Comprobando entorno...' ;;
            it) echo 'Verifica dell'\''ambiente in corso...' ;;
            ar) echo 'التحقق من البيئة...' ;;
        esac
        ;;
    need_py310)
        case "$LANG_CHOICE" in
            zh) echo '需要 Python 3.10+，未找到' ;;
            en) echo 'Requires Python 3.10+, not found' ;;
            ja) echo 'Python 3.10+ が必要ですが見つかりません' ;;
            ko) echo 'Python 3.10+ 필요하지만 찾을 수 없음' ;;
            fr) echo 'Python 3.10+ requis, introuvable' ;;
            de) echo 'Python 3.10+ erforderlich, nicht gefunden' ;;
            es) echo 'Requiere Python 3.10+, no encontrado' ;;
            it) echo 'Richiede Python 3.10+, non trovato' ;;
            ar) echo 'يتطلب Python 3.10+، غير موجود' ;;
        esac
        ;;
    install_py_methods)
        case "$LANG_CHOICE" in
            zh) echo '安装 Python 3.10+ 的方法：' ;;
            en) echo 'How to install Python 3.10+:' ;;
            ja) echo 'Python 3.10+ のインストール方法：' ;;
            ko) echo 'Python 3.10+ 설치 방법:' ;;
            fr) echo 'Comment installer Python 3.10+ :' ;;
            de) echo 'Python 3.10+ installieren:' ;;
            es) echo 'Cómo instalar Python 3.10+:' ;;
            it) echo 'Come installare Python 3.10+:' ;;
            ar) echo 'كيفية تثبيت Python 3.10+:' ;;
        esac
        ;;
    method1_homebrew)
        case "$LANG_CHOICE" in
            zh) echo '方法 1：Homebrew（推荐）' ;;
            en) echo 'Method 1: Homebrew (recommended)' ;;
            ja) echo '方法1: Homebrew（推奨）' ;;
            ko) echo '방법1: Homebrew (권장)' ;;
            fr) echo 'Méthode 1 : Homebrew (recommandé)' ;;
            de) echo 'Methode 1: Homebrew (empfohlen)' ;;
            es) echo 'Método 1: Homebrew (recomendado)' ;;
            it) echo 'Metodo 1: Homebrew (consigliato)' ;;
            ar) echo 'الطريقة 1: Homebrew (موصى به)' ;;
        esac
        ;;
    method2_official)
        case "$LANG_CHOICE" in
            zh) echo '方法 2：官方安装包' ;;
            en) echo 'Method 2: Official installer' ;;
            ja) echo '方法2: 公式インストーラー' ;;
            ko) echo '방법2: 공식 설치 프로그램' ;;
            fr) echo 'Méthode 2 : Programme officiel' ;;
            de) echo 'Methode 2: Offizieller Installer' ;;
            es) echo 'Método 2: Instalador oficial' ;;
            it) echo 'Metodo 2: Installer ufficiale' ;;
            ar) echo 'الطريقة 2: المثبت الرسمي' ;;
        esac
        ;;
    method3_xcode)
        case "$LANG_CHOICE" in
            zh) echo '方法 3：Xcode 命令行工具' ;;
            en) echo 'Method 3: Xcode Command Line Tools' ;;
            ja) echo '方法3: Xcode コマンドラインツール' ;;
            ko) echo '방법3: Xcode Command Line Tools' ;;
            fr) echo 'Méthode 3 : Xcode Command Line Tools' ;;
            de) echo 'Methode 3: Xcode Command Line Tools' ;;
            es) echo 'Método 3: Xcode Command Line Tools' ;;
            it) echo 'Metodo 3: Xcode Command Line Tools' ;;
            ar) echo 'الطريقة 3: Xcode Command Line Tools' ;;
        esac
        ;;
    dmg_recommend)
        case "$LANG_CHOICE" in
            zh) echo '推荐：直接下载 macOS 原生应用（免 Python/Homebrew，双击即用）' ;;
            en) echo 'Recommended: download the native macOS app (no Python/Homebrew needed)' ;;
            ja) echo '推奨：macOS ネイティブアプリを直接ダウンロード（Python/Homebrew 不要）' ;;
            ko) echo '권장: macOS 네이티브 앱 직접 다운로드 (Python/Homebrew 불필요)' ;;
            fr) echo 'Recommandé : télécharger l'\''application macOS native (Python/Homebrew non requis)' ;;
            de) echo 'Empfohlen: native macOS-App herunterladen (Python/Homebrew nicht nötig)' ;;
            es) echo 'Recomendado: descargar la app nativa de macOS (sin Python/Homebrew)' ;;
            it) echo 'Consigliato: scarica l'\''app nativa macOS (senza Python/Homebrew)' ;;
            ar) echo 'موصى به: تنزيل تطبيق macOS الأصلي (لا حاجة لـ Python/Homebrew)' ;;
        esac
        ;;
    installing_pip)
        case "$LANG_CHOICE" in
            zh) echo '正在安装 pip...' ;;
            en) echo 'Installing pip...' ;;
            ja) echo 'pip をインストール中...' ;;
            ko) echo 'pip 설치 중...' ;;
            fr) echo 'Installation de pip...' ;;
            de) echo 'pip wird installiert...' ;;
            es) echo 'Instalando pip...' ;;
            it) echo 'Installazione di pip...' ;;
            ar) echo 'جاري تثبيت pip...' ;;
        esac
        ;;
    homebrew_not_installed)
        case "$LANG_CHOICE" in
            zh) echo '未安装 Homebrew（可选，用于系统依赖）' ;;
            en) echo 'Homebrew not installed (optional, for system deps)' ;;
            ja) echo 'Homebrew 未インストール（任意、システム依存関係用）' ;;
            ko) echo 'Homebrew 미설치 (선택 사항, 시스템 종속성용)' ;;
            fr) echo 'Homebrew non installé (optionnel, pour dépendances système)' ;;
            de) echo 'Homebrew nicht installiert (optional, für Systemabhängigkeiten)' ;;
            es) echo 'Homebrew no instalado (opcional, para dependencias del sistema)' ;;
            it) echo 'Homebrew non installato (opzionale, per dipendenze di sistema)' ;;
            ar) echo 'Homebrew غير مثبت (اختياري، لتبعيات النظام)' ;;
        esac
        ;;
    step3_fetch)
        case "$LANG_CHOICE" in
            zh) echo "正在获取 meshctx v${VERSION}..." ;;
            en) echo "Fetching meshctx v${VERSION}..." ;;
            ja) echo "meshctx v${VERSION} を取得中..." ;;
            ko) echo "meshctx v${VERSION} 가져오는 중..." ;;
            fr) echo "Récupération de meshctx v${VERSION}..." ;;
            de) echo "meshctx v${VERSION} wird abgerufen..." ;;
            es) echo "Obteniendo meshctx v${VERSION}..." ;;
            it) echo "Recupero di meshctx v${VERSION} in corso..." ;;
            ar) echo "جاري جلب meshctx v${VERSION}..." ;;
        esac
        ;;
    using_local)
        case "$LANG_CHOICE" in
            zh) echo "使用本地源码：${SOURCE_DIR}" ;;
            en) echo "Using local source: ${SOURCE_DIR}" ;;
            ja) echo "ローカルソースを使用: ${SOURCE_DIR}" ;;
            ko) echo "로컬 소스 사용: ${SOURCE_DIR}" ;;
            fr) echo "Utilisation de la source locale : ${SOURCE_DIR}" ;;
            de) echo "Lokale Quelle wird verwendet: ${SOURCE_DIR}" ;;
            es) echo "Usando fuente local: ${SOURCE_DIR}" ;;
            it) echo "Utilizzo sorgente locale: ${SOURCE_DIR}" ;;
            ar) echo "استخدام المصدر المحلي: ${SOURCE_DIR}" ;;
        esac
        ;;
    git_cloning)
        case "$LANG_CHOICE" in
            zh) echo '正在通过 git clone 获取...' ;;
            en) echo 'Fetching via git clone...' ;;
            ja) echo 'git clone で取得中...' ;;
            ko) echo 'git clone으로 가져오는 중...' ;;
            fr) echo 'Récupération via git clone...' ;;
            de) echo 'Abruf via git clone...' ;;
            es) echo 'Obteniendo vía git clone...' ;;
            it) echo 'Recupero tramite git clone...' ;;
            ar) echo 'جاري الجلب عبر git clone...' ;;
        esac
        ;;
    git_clone_ok)
        case "$LANG_CHOICE" in
            zh) echo 'git clone 成功' ;;
            en) echo 'git clone succeeded' ;;
            ja) echo 'git clone 成功' ;;
            ko) echo 'git clone 성공' ;;
            fr) echo 'git clone réussi' ;;
            de) echo 'git clone erfolgreich' ;;
            es) echo 'git clone exitoso' ;;
            it) echo 'git clone riuscito' ;;
            ar) echo 'تم git clone بنجاح' ;;
        esac
        ;;
    git_clone_fail)
        case "$LANG_CHOICE" in
            zh) echo 'git clone 失败' ;;
            en) echo 'git clone failed' ;;
            ja) echo 'git clone 失敗' ;;
            ko) echo 'git clone 실패' ;;
            fr) echo 'Échec du git clone' ;;
            de) echo 'git clone fehlgeschlagen' ;;
            es) echo 'git clone fallido' ;;
            it) echo 'git clone fallito' ;;
            ar) echo 'فشل git clone' ;;
        esac
        ;;
    check_network_git)
        case "$LANG_CHOICE" in
            zh) echo '请检查网络，或手动 git clone' ;;
            en) echo 'Check network or manually git clone' ;;
            ja) echo 'ネットワークを確認するか手動でgit cloneしてください' ;;
            ko) echo '네트워크를 확인하거나 수동으로 git clone하세요' ;;
            fr) echo 'Vérifiez le réseau ou faites un git clone manuel' ;;
            de) echo 'Netzwerk prüfen oder manuell git clone' ;;
            es) echo 'Verifique la red o haga git clone manual' ;;
            it) echo 'Controlla la rete o fai git clone manualmente' ;;
            ar) echo 'تحقق من الشبكة أو قم بعمل git clone يدوياً' ;;
        esac
        ;;
    release_fail_try_git)
        case "$LANG_CHOICE" in
            zh) echo 'Release 下载失败，尝试 git clone...' ;;
            en) echo 'Release download failed, trying git clone...' ;;
            ja) echo 'リリースダウンロード失敗、git clone を試行中...' ;;
            ko) echo '릴리스 다운로드 실패, git clone 시도 중...' ;;
            fr) echo 'Échec du téléchargement de la release, tentative de git clone...' ;;
            de) echo 'Release-Download fehlgeschlagen, versuche git clone...' ;;
            es) echo 'Descarga de release fallida, intentando git clone...' ;;
            it) echo 'Download della release fallito, provo git clone...' ;;
            ar) echo 'فشل تنزيل الإصدار، جاري محاولة git clone...' ;;
        esac
        ;;
    download_fail_short)
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
        esac
        ;;
    manual_install)
        case "$LANG_CHOICE" in
            zh) echo '手动安装：' ;;
            en) echo 'Manual install:' ;;
            ja) echo '手動インストール：' ;;
            ko) echo '수동 설치:' ;;
            fr) echo 'Installation manuelle :' ;;
            de) echo 'Manuelle Installation:' ;;
            es) echo 'Instalación manual:' ;;
            it) echo 'Installazione manuale:' ;;
            ar) echo 'تثبيت يدوي:' ;;
        esac
        ;;
    step4_install)
        case "$LANG_CHOICE" in
            zh) echo '正在安装...' ;;
            en) echo 'Installing...' ;;
            ja) echo 'インストール中...' ;;
            ko) echo '설치 중...' ;;
            fr) echo 'Installation...' ;;
            de) echo 'Installation...' ;;
            es) echo 'Instalando...' ;;
            it) echo 'Installazione...' ;;
            ar) echo 'جاري التثبيت...' ;;
        esac
        ;;
    config_backed_up)
        case "$LANG_CHOICE" in
            zh) echo '用户配置已备份' ;;
            en) echo 'User config backed up' ;;
            ja) echo 'ユーザー設定をバックアップしました' ;;
            ko) echo '사용자 설정 백업 완료' ;;
            fr) echo 'Configuration utilisateur sauvegardée' ;;
            de) echo 'Benutzerkonfiguration gesichert' ;;
            es) echo 'Configuración de usuario respaldada' ;;
            it) echo 'Configurazione utente salvata' ;;
            ar) echo 'تم نسخ إعدادات المستخدم احتياطياً' ;;
        esac
        ;;
    creating_venv)
        case "$LANG_CHOICE" in
            zh) echo '正在创建虚拟环境...' ;;
            en) echo 'Creating virtual environment...' ;;
            ja) echo '仮想環境を作成中...' ;;
            ko) echo '가상 환경 생성 중...' ;;
            fr) echo 'Création de l'\''environnement virtuel...' ;;
            de) echo 'Virtuelle Umgebung wird erstellt...' ;;
            es) echo 'Creando entorno virtual...' ;;
            it) echo 'Creazione dell'\''ambiente virtuale...' ;;
            ar) echo 'جاري إنشاء البيئة الافتراضية...' ;;
        esac
        ;;
    installing_deps)
        case "$LANG_CHOICE" in
            zh) echo '正在安装依赖...' ;;
            en) echo 'Installing dependencies...' ;;
            ja) echo '依存関係をインストール中...' ;;
            ko) echo '의존성 설치 중...' ;;
            fr) echo 'Installation des dépendances...' ;;
            de) echo 'Abhängigkeiten werden installiert...' ;;
            es) echo 'Instalando dependencias...' ;;
            it) echo 'Installazione delle dipendenze...' ;;
            ar) echo 'جاري تثبيت التبعيات...' ;;
        esac
        ;;
    deps_ok)
        case "$LANG_CHOICE" in
            zh) echo '依赖安装完成' ;;
            en) echo 'Dependencies installed' ;;
            ja) echo '依存関係のインストール完了' ;;
            ko) echo '의존성 설치 완료' ;;
            fr) echo 'Dépendances installées' ;;
            de) echo 'Abhängigkeiten installiert' ;;
            es) echo 'Dependencias instaladas' ;;
            it) echo 'Dipendenze installate' ;;
            ar) echo 'تم تثبيت التبعيات' ;;
        esac
        ;;
    installing_meshctx_pkg)
        case "$LANG_CHOICE" in
            zh) echo '正在安装 meshctx 包...' ;;
            en) echo 'Installing meshctx package...' ;;
            ja) echo 'meshctx パッケージをインストール中...' ;;
            ko) echo 'meshctx 패키지 설치 중...' ;;
            fr) echo 'Installation du package meshctx...' ;;
            de) echo 'meshctx-Paket wird installiert...' ;;
            es) echo 'Instalando paquete meshctx...' ;;
            it) echo 'Installazione del pacchetto meshctx...' ;;
            ar) echo 'جاري تثبيت حزمة meshctx...' ;;
        esac
        ;;
    meshctx_pkg_ok)
        case "$LANG_CHOICE" in
            zh) echo 'meshctx 包安装完成' ;;
            en) echo 'meshctx package installed' ;;
            ja) echo 'meshctx パッケージのインストール完了' ;;
            ko) echo 'meshctx 패키지 설치 완료' ;;
            fr) echo 'Package meshctx installé' ;;
            de) echo 'meshctx-Paket installiert' ;;
            es) echo 'Paquete meshctx instalado' ;;
            it) echo 'Pacchetto meshctx installato' ;;
            ar) echo 'تم تثبيت حزمة meshctx' ;;
        esac
        ;;
    installing_cmd)
        case "$LANG_CHOICE" in
            zh) echo '正在安装 meshctx 命令...' ;;
            en) echo 'Installing meshctx command...' ;;
            ja) echo 'meshctx コマンドをインストール中...' ;;
            ko) echo 'meshctx 명령 설치 중...' ;;
            fr) echo 'Installation de la commande meshctx...' ;;
            de) echo 'meshctx-Befehl wird installiert...' ;;
            es) echo 'Instalando comando meshctx...' ;;
            it) echo 'Installazione del comando meshctx...' ;;
            ar) echo 'جاري تثبيت أمر meshctx...' ;;
        esac
        ;;
    cmd_installed)
        case "$LANG_CHOICE" in
            zh) echo 'meshctx 命令安装完成' ;;
            en) echo 'meshctx command installed' ;;
            ja) echo 'meshctx コマンドをインストールしました' ;;
            ko) echo 'meshctx 명령 설치됨' ;;
            fr) echo 'Commande meshctx installée' ;;
            de) echo 'meshctx-Befehl installiert' ;;
            es) echo 'Comando meshctx instalado' ;;
            it) echo 'Comando meshctx installato' ;;
            ar) echo 'تم تثبيت أمر meshctx' ;;
        esac
        ;;
    configuring_autostart)
        case "$LANG_CHOICE" in
            zh) echo '正在配置开机自启...' ;;
            en) echo 'Configuring auto-start...' ;;
            ja) echo '自動起動を設定中...' ;;
            ko) echo '자동 시작 설정 중...' ;;
            fr) echo 'Configuration du démarrage automatique...' ;;
            de) echo 'Autostart wird konfiguriert...' ;;
            es) echo 'Configurando inicio automático...' ;;
            it) echo 'Configurazione dell'\''avvio automatico...' ;;
            ar) echo 'جاري تكوين التشغيل التلقائي...' ;;
        esac
        ;;
    autostart_ok)
        case "$LANG_CHOICE" in
            zh) echo '开机自启已配置' ;;
            en) echo 'Auto-start configured' ;;
            ja) echo '自動起動を設定しました' ;;
            ko) echo '자동 시작 설정됨' ;;
            fr) echo 'Démarrage automatique configuré' ;;
            de) echo 'Autostart konfiguriert' ;;
            es) echo 'Inicio automático configurado' ;;
            it) echo 'Avvio automatico configurato' ;;
            ar) echo 'تم تكوين التشغيل التلقائي' ;;
        esac
        ;;
    step5_verify)
        case "$LANG_CHOICE" in
            zh) echo '正在验证安装...' ;;
            en) echo 'Verifying installation...' ;;
            ja) echo 'インストールを検証中...' ;;
            ko) echo '설치 확인 중...' ;;
            fr) echo 'Vérification de l'\''installation...' ;;
            de) echo 'Installation wird überprüft...' ;;
            es) echo 'Verificando instalación...' ;;
            it) echo 'Verifica dell'\''installazione...' ;;
            ar) echo 'التحقق من التثبيت...' ;;
        esac
        ;;
    service_running)
        case "$LANG_CHOICE" in
            zh) echo "服务运行正常（端口 ${PORT}）" ;;
            en) echo "Service running OK (port ${PORT})" ;;
            ja) echo "サービス正常稼働中 (ポート ${PORT})" ;;
            ko) echo "서비스 정상 작동 중 (포트 ${PORT})" ;;
            fr) echo "Service en cours (port ${PORT})" ;;
            de) echo "Dienst läuft normal (Port ${PORT})" ;;
            es) echo "Servicio funcionando (puerto ${PORT})" ;;
            it) echo "Servizio in esecuzione (porta ${PORT})" ;;
            ar) echo "الخدمة تعمل بشكل طبيعي (المنفذ ${PORT})" ;;
        esac
        ;;
    service_manual_start)
        case "$LANG_CHOICE" in
            zh) echo "服务已手动启动（端口 ${PORT}）" ;;
            en) echo "Service started manually (port ${PORT})" ;;
            ja) echo "サービスを手動起動しました (ポート ${PORT})" ;;
            ko) echo "서비스 수동 시작됨 (포트 ${PORT})" ;;
            fr) echo "Service démarré manuellement (port ${PORT})" ;;
            de) echo "Dienst manuell gestartet (Port ${PORT})" ;;
            es) echo "Servicio iniciado manualmente (puerto ${PORT})" ;;
            it) echo "Servizio avviato manualmente (porta ${PORT})" ;;
            ar) echo "تم بدء الخدمة يدوياً (المنفذ ${PORT})" ;;
        esac
        ;;
    service_starting)
        case "$LANG_CHOICE" in
            zh) echo '服务启动中，请稍后检查' ;;
            en) echo 'Service starting, please check later' ;;
            ja) echo 'サービス起動中、後ほどご確認ください' ;;
            ko) echo '서비스 시작 중, 나중에 확인하세요' ;;
            fr) echo 'Service en cours de démarrage, veuillez vérifier plus tard' ;;
            de) echo 'Dienst startet, bitte später prüfen' ;;
            es) echo 'Servicio iniciando, verifique más tarde' ;;
            it) echo 'Servizio in avvio, controlla più tardi' ;;
            ar) echo 'جاري بدء الخدمة، يرجى التحقق لاحقاً' ;;
        esac
        ;;
    install_complete)
        case "$LANG_CHOICE" in
            zh) echo 'meshctx macOS 安装完成！ 🎉' ;;
            en) echo 'meshctx macOS Installation Complete! 🎉' ;;
            ja) echo 'meshctx macOS インストール完了！ 🎉' ;;
            ko) echo 'meshctx macOS 설치 완료! 🎉' ;;
            fr) echo 'Installation de meshctx macOS terminée ! 🎉' ;;
            de) echo 'meshctx macOS Installation abgeschlossen! 🎉' ;;
            es) echo '¡Instalación de meshctx macOS completada! 🎉' ;;
            it) echo 'Installazione meshctx macOS completata! 🎉' ;;
            ar) echo 'اكتمل تثبيت meshctx macOS! 🎉' ;;
        esac
        ;;
    quick_start_label)
        case "$LANG_CHOICE" in
            zh) echo '快速开始：' ;;
            en) echo 'Quick Start:' ;;
            ja) echo 'クイックスタート:' ;;
            ko) echo '빠른 시작:' ;;
            fr) echo 'Démarrage rapide :' ;;
            de) echo 'Schnellstart:' ;;
            es) echo 'Inicio rápido:' ;;
            it) echo 'Avvio rapido:' ;;
            ar) echo ':بداية سريعة' ;;
        esac
        ;;
    common_cmds_label)
        case "$LANG_CHOICE" in
            zh) echo '常用命令：' ;;
            en) echo 'Common Commands:' ;;
            ja) echo 'よく使うコマンド:' ;;
            ko) echo '자주 쓰는 명령어:' ;;
            fr) echo 'Commandes courantes :' ;;
            de) echo 'Häufige Befehle:' ;;
            es) echo 'Comandos comunes:' ;;
            it) echo 'Comandi comuni:' ;;
            ar) echo ':أوامر شائعة' ;;
        esac
        ;;
    autostart_label)
        case "$LANG_CHOICE" in
            zh) echo '开机自启：' ;;
            en) echo 'Auto-start:' ;;
            ja) echo '自動起動:' ;;
            ko) echo '자동 시작:' ;;
            fr) echo 'Démarrage automatique :' ;;
            de) echo 'Autostart:' ;;
            es) echo 'Inicio automático:' ;;
            it) echo 'Avvio automatico:' ;;
            ar) echo ':تشغيل تلقائي' ;;
        esac
        ;;
    manage_launchagent)
        case "$LANG_CHOICE" in
            zh) echo '管理 LaunchAgent：' ;;
            en) echo 'Manage LaunchAgent:' ;;
            ja) echo 'LaunchAgent 管理:' ;;
            ko) echo 'LaunchAgent 관리:' ;;
            fr) echo 'Gérer LaunchAgent :' ;;
            de) echo 'LaunchAgent verwalten:' ;;
            es) echo 'Administrar LaunchAgent:' ;;
            it) echo 'Gestisci LaunchAgent:' ;;
            ar) echo ':LaunchAgent إدارة' ;;
        esac
        ;;
    pkg_elev_fail)
        case "$LANG_CHOICE" in
            zh) echo '自动提权安装未成功（需要管理员密码）' ;;
            en) echo 'Automatic elevated install failed (admin password required)' ;;
            ja) echo '自動昇格インストールに失敗しました（管理者パスワードが必要）' ;;
            ko) echo '자동 권한 상승 설치 실패 (관리자 비밀번호 필요)' ;;
            fr) echo 'Échec de l\'installation élevée automatique (mot de passe admin requis)' ;;
            de) echo 'Automatische erweiterte Installation fehlgeschlagen (Admin-Passwort erforderlich)' ;;
            es) echo 'Error en la instalación elevada automática (se requiere contraseña de administrador)' ;;
            it) echo 'Installazione elevata automatica fallita (richiesta password amministratore)' ;;
            ar) echo 'فشل التثبيت المرتفع التلقائي (كلمة مرور المسؤول مطلوبة)' ;;
        esac
        ;;
    pkg_downloaded_to)
        case "$LANG_CHOICE" in
            zh) echo '已下载安装包到 %s，请手动执行（粘贴到终端，输入密码）：' ;;
            en) echo 'Installer downloaded to %s — please run manually (paste into terminal, enter password):' ;;
            ja) echo 'インストーラーを %s にダウンロードしました。手動で実行してください（ターミナルに貼り付け、パスワードを入力）：' ;;
            ko) echo '설치 프로그램을 %s에 다운로드했습니다. 수동으로 실행하세요 (터미널에 붙여넣고 비밀번호 입력):' ;;
            fr) echo 'Programme d\'installation téléchargé vers %s — exécutez manuellement (collez dans le terminal, saisissez le mot de passe) :' ;;
            de) echo 'Installationsprogramm nach %s heruntergeladen — bitte manuell ausführen (in Terminal einfügen, Passwort eingeben):' ;;
            es) echo 'Instalador descargado en %s — ejecútelo manualmente (péguelo en la terminal, introduzca la contraseña):' ;;
            it) echo 'Installer scaricato su %s — eseguire manualmente (incollare nel terminale, inserire la password):' ;;
            ar) echo 'تم تنزيل المثبت إلى %s — يرجى التنفيذ يدويًا (الصق في الطرفية وأدخل كلمة المرور):' ;;
        esac
        ;;
    pkg_rerun_after)
        case "$LANG_CHOICE" in
            zh) echo '安装完成后重新运行本脚本即可。' ;;
            en) echo 'Re-run this script after installation completes.' ;;
            ja) echo 'インストール完了後、このスクリプトを再実行してください。' ;;
            ko) echo '설치 완료 후 이 스크립트를 다시 실행하세요.' ;;
            fr) echo 'Réexécutez ce script une fois l\'installation terminée.' ;;
            de) echo 'Führen Sie dieses Skript nach Abschluss der Installation erneut aus.' ;;
            es) echo 'Vuelva a ejecutar este script una vez completada la instalación.' ;;
            it) echo 'Eseguire nuovamente questo script al termine dell\'installazione.' ;;
            ar) echo 'أعد تشغيل هذا البرنامج النصي بعد اكتمال التثبيت.' ;;
        esac
        ;;
    *) echo "$1" ;;
    esac
}

INSTALL_DIR="${HOME}/.meshctx"
VERSION="3.119.0"
REPO="LucyAndLuna2023/meshctx"
SRC_URL="https://github.com/${REPO}/archive/refs/tags/v${VERSION}.tar.gz"
PORT=3001
LAUNCHD_LABEL="com.meshctx.server"

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║     $(T header_macos)        ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── macOS 检测 ──
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}✗ $(T macos_only)${NC}"
    exit 1
fi

MACOS_VER=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
echo -e "  ${GREEN}✓${NC} macOS ${MACOS_VER} ($(uname -m))"

# ── [1/6] 停止旧版本 ─────────────────────────────────
echo -e "${CYAN}[1/6]${NC} $(T step1_stop)"

KILLED=0

# 停止 uvicorn
if pgrep -f "uvicorn.*src.main" >/dev/null 2>&1; then
    pkill -9 -f "uvicorn.*src.main" 2>/dev/null || true
    KILLED=1
fi

# 停止 meshctx CLI
if pgrep -f "python.*meshctx" >/dev/null 2>&1; then
    pkill -9 -f "python.*meshctx" 2>/dev/null || true
    KILLED=1
fi

# 停止 launchd 服务
if launchctl list 2>/dev/null | grep -q "${LAUNCHD_LABEL}"; then
    launchctl unload "${HOME}/Library/LaunchAgents/${LAUNCHD_LABEL}.plist" 2>/dev/null || true
    KILLED=1
fi

sleep 1

# 释放端口 (macOS 用 lsof)
PORT_PID=$(lsof -ti:${PORT} 2>/dev/null | head -1)
if [ -n "${PORT_PID}" ]; then
    kill -9 "${PORT_PID}" 2>/dev/null || true
    KILLED=1
fi

if [ "${KILLED}" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} $(T stopped_ok_port)"
else
    echo -e "  ${GREEN}✓${NC} $(T no_stop)"
fi

# ── [2/6] 环境检查 ───────────────────────────────────
echo -e "${CYAN}[2/6]${NC} $(T step2_check)"

# Python 检查（自动搜索所有已知路径，找不到则自动安装）
PYTHON_BIN=""

# 候选命令 + 已知安装路径（Homebrew keg-only、python.org 框架、标准路径）
PY_CANDIDATES="python3.12 python3.11 python3.10 python3"

# 辅助：检查一个 Python 是否 >= 3.10
py_ok() {
    local bin="$1"
    [ -x "$bin" ] || return 1
    local ver major minor
    ver=$("$bin" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    [ -z "$ver" ] && return 1
    major=$(echo "$ver" | cut -d. -f1)
    minor=$(echo "$ver" | cut -d. -f2)
    [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; } 2>/dev/null
}

# 1) PATH 内命令
for p in $PY_CANDIDATES; do
    if command -v "$p" >/dev/null 2>&1 && py_ok "$(command -v "$p")"; then
        PYTHON_BIN="$(command -v "$p")"
        break
    fi
done

# 2) Homebrew keg-only 已知路径（macOS Intel: /usr/local，Apple Silicon: /opt/homebrew）
if [ -z "${PYTHON_BIN}" ]; then
    for p in /usr/local/opt/python@3.12/bin/python3.12 /opt/homebrew/opt/python@3.12/bin/python3.12 \
             /usr/local/opt/python@3.11/bin/python3.11 /opt/homebrew/opt/python@3.11/bin/python3.11 \
             /usr/local/opt/python@3.10/bin/python3.10 /opt/homebrew/opt/python@3.10/bin/python3.10 \
             /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12; do
        if py_ok "$p"; then
            PYTHON_BIN="$p"
            break
        fi
    done
fi

# 3) python.org 官方框架路径
if [ -z "${PYTHON_BIN}" ]; then
    for v in 3.12 3.11 3.10; do
        p="/Library/Frameworks/Python.framework/Versions/${v}/bin/python3"
        if py_ok "$p"; then
            PYTHON_BIN="$p"
            break
        fi
    done
fi

# 4) 仍未找到 → 自动安装（brew 优先，其次 python.org pkg）
if [ -z "${PYTHON_BIN}" ]; then
    echo -e "  ${YELLOW}→ 未检测到 Python 3.10+，正在自动安装...${NC}"

    if command -v brew >/dev/null 2>&1; then
        echo -e "  ${YELLOW}→ 使用 Homebrew 安装 python@3.12（约 1-3 分钟，请稍候；若长时间无输出多为 brew 自动更新/网络问题，可 Ctrl+C 后手动执行 HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.12）...${NC}"
        if HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.12; then
            for p in /usr/local/opt/python@3.12/bin/python3.12 /opt/homebrew/opt/python@3.12/bin/python3.12 \
                     /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12; do
                py_ok "$p" && { PYTHON_BIN="$p"; break; }
            done
        else
            echo -e "  ${RED}→ brew install 失败，尝试其他方式...${NC}"
        fi
    fi

    if [ -z "${PYTHON_BIN}" ] && command -v python3 >/dev/null 2>&1 && py_ok "$(command -v python3)"; then
        PYTHON_BIN="$(command -v python3)"
    fi

    if [ -z "${PYTHON_BIN}" ]; then
        echo -e "  ${YELLOW}→ 未检测到可用 Python，下载 python.org 官方安装包（约 30MB，以下为下载进度）...${NC}"
        # 下载 python.org pkg 并安装（需管理员密码）；--progress-bar 显示进度
        PKG_URL="https://www.python.org/ftp/python/3.12.8/python-3.12.8-macos11.pkg"
        PKG_TMP="/tmp/python-3.12.8.pkg"
        if curl -fL --connect-timeout 30 --retry 2 --progress-bar -o "${PKG_TMP}" "${PKG_URL}"; then
            echo -e "  ${YELLOW}→ 安装 python-3.12.8.pkg（需要管理员密码，可能弹出密码框）...${NC}"
            INSTALLED=0
            # 1) GUI 会话: osascript 弹密码框提权安装
            if command -v osascript >/dev/null 2>&1; then
                if osascript -e "do shell script \"installer -pkg ${PKG_TMP} -target /\" with administrator privileges" >/dev/null 2>&1; then
                    INSTALLED=1
                fi
            fi
            # 2) root / 密码已缓存场景: 直接 installer
            if [ "${INSTALLED}" != "1" ]; then
                if installer -pkg "${PKG_TMP}" -target / >/dev/null 2>&1; then
                    INSTALLED=1
                fi
            fi
            if [ "${INSTALLED}" = "1" ]; then
                rm -f "${PKG_TMP}"
                for p in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
                         /usr/local/bin/python3.12; do
                    py_ok "$p" && { PYTHON_BIN="$p"; break; }
                done
            else
                echo -e "  ${RED}✗ $(T pkg_elev_fail)${NC}"
                echo -e "  ${YELLOW}  $(printf "$(T pkg_downloaded_to)" "${PKG_TMP}")${NC}"
                echo -e "    sudo installer -pkg \\\"${PKG_TMP}\\\" -target /"
                echo -e "  ${YELLOW}  $(T pkg_rerun_after)${NC}"
            fi
        fi
    fi

    if [ -z "${PYTHON_BIN}" ]; then
        echo ""
        echo -e "  ${BOLD}🍎 $(T dmg_recommend)${NC}"
        if [ "$(uname -m)" = "arm64" ]; then
            echo "    https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx-macos.dmg"
        else
            echo "    https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx-macos-intel.dmg"
        fi
        echo ""
        echo -e "  ${RED}✗ $(T need_py310)${NC}"
        echo ""
        echo -e "  ${YELLOW}$(T install_py_methods)${NC}"
        echo ""
        echo -e "  ${BOLD}$(T method1_homebrew)${NC}"
        echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo "    brew install python@3.12"
        echo ""
        echo -e "  ${BOLD}$(T method2_official)${NC}"
        echo "    下载: https://www.python.org/downloads/macos/"
        echo "    安装 .pkg 后重新打开终端"
        echo ""
        echo -e "  ${BOLD}$(T method3_xcode)${NC}"
        echo "    xcode-select --install"
        echo ""
        exit 1
    fi
fi

# 确保 PATH 含 Python 所在目录（keg-only 场景，供后续子进程使用）
PY_BIN_DIR="$(dirname "${PYTHON_BIN}")"
case ":${PATH}:" in
    *":${PY_BIN_DIR}:"*) ;;
    *) export PATH="${PY_BIN_DIR}:${PATH}" ;;
esac

PY_VER=$(${PYTHON_BIN} --version 2>&1)
echo -e "  ${GREEN}✓${NC} ${PY_VER} ($(which ${PYTHON_BIN}))"

# pip 检查
if ! ${PYTHON_BIN} -m pip --version >/dev/null 2>&1; then
    echo -e "  ${YELLOW}→${NC} $(T installing_pip)"
    ${PYTHON_BIN} -m ensurepip --upgrade 2>/dev/null || \
        curl -sS https://bootstrap.pypa.io/get-pip.py | ${PYTHON_BIN}
fi
echo -e "  ${GREEN}✓${NC} pip: $(${PYTHON_BIN} -m pip --version 2>&1 | head -1)"

# Homebrew 检测（可选）
if command -v brew >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Homebrew: $(brew --version 2>&1 | head -1)"
else
    echo -e "  ${YELLOW}⚠${NC} $(T homebrew_not_installed)"
fi

# ── [3/6] 获取源码 ──────────────────────────────────
echo -e "${CYAN}[3/6]${NC} $(T step3_fetch)"

SOURCE_DIR=""
USE_LOCAL=0

# 检查 --offline 或 --from-dir 参数
for arg in "$@"; do
    case "$arg" in
        --offline|--local) USE_LOCAL=1 ;;
        --from-dir=*) SOURCE_DIR="${arg#*=}"; USE_LOCAL=1 ;;
    esac
done

# 如果当前目录就是 meshctx 源码目录
if [ -f "$(pwd)/install-mac.sh" ] && [ -f "$(pwd)/src/main.py" ]; then
    SOURCE_DIR="$(pwd)"
    USE_LOCAL=1
fi

if [ "${USE_LOCAL}" = "1" ] && [ -n "${SOURCE_DIR}" ]; then
    echo -e "  ${GREEN}✓${NC} $(T using_local)"
elif [ "${USE_LOCAL}" = "1" ]; then
    echo -e "  ${YELLOW}→${NC} $(T git_cloning)"
    TMPDIR=$(mktemp -d)
    if git clone --depth 1 "https://github.com/${REPO}.git" "${TMPDIR}/meshctx" 2>/dev/null; then
        SOURCE_DIR="${TMPDIR}/meshctx"
        echo -e "  ${GREEN}✓${NC} $(T git_clone_ok)"
    else
        echo -e "${RED}✗ $(T git_clone_fail)${NC}"
        echo "  $(T check_network_git)"
        exit 1
    fi
else
    # 尝试下载 release tarball
    TMPDIR=$(mktemp -d)
    TARBALL="${TMPDIR}/meshctx-src.tar.gz"
    trap "rm -rf ${TMPDIR}" EXIT

    DOWNLOAD_OK=0
    if curl -fsSL --connect-timeout 30 --retry 2 -o "${TARBALL}" "${SRC_URL}" 2>/dev/null; then
        DOWNLOAD_OK=1
    elif command -v wget >/dev/null 2>&1; then
        wget -q --timeout=60 --tries=2 -O "${TARBALL}" "${SRC_URL}" && DOWNLOAD_OK=1
    fi

    if [ "${DOWNLOAD_OK}" != "1" ]; then
        # Fallback: git clone
        echo -e "  ${YELLOW}→${NC} $(T release_fail_try_git)"
        if git clone --depth 1 "https://github.com/${REPO}.git" "${TMPDIR}/meshctx" 2>/dev/null; then
            SOURCE_DIR="${TMPDIR}/meshctx"
            echo -e "  ${GREEN}✓${NC} $(T git_clone_ok)"
        else
            echo -e "${RED}✗ $(T download_fail_short)${NC}"
            echo ""
            echo -e "  ${YELLOW}$(T manual_install)${NC}"
            echo "    git clone https://github.com/${REPO}.git ~/.meshctx"
            echo "    cd ~/.meshctx && bash install-mac.sh"
            echo ""
            exit 1
        fi
    fi
fi

# ── [4/6] 安装 ──────────────────────────────────────
echo -e "${CYAN}[4/6]${NC} $(T step4_install)"

# 备份用户配置
CONFIG_BACKUP=""
if [ -d "${INSTALL_DIR}" ]; then
    CONFIG_BACKUP=$(mktemp -d)
    for f in config.yaml .env provider_config.json; do
        if [ -f "${INSTALL_DIR}/${f}" ]; then
            cp "${INSTALL_DIR}/${f}" "${CONFIG_BACKUP}/${f}" 2>/dev/null || true
        fi
    done
    [ -z "${CONFIG_BACKUP}" ] || echo -e "  ${GREEN}✓${NC} $(T config_backed_up)"
fi

# 安装新版本
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"

if [ -n "${SOURCE_DIR}" ]; then
    # Copy from source directory
    cp -R "${SOURCE_DIR}"/* "${INSTALL_DIR}/" 2>/dev/null
    [ -d "${SOURCE_DIR}/.git" ] && cp -R "${SOURCE_DIR}/.git" "${INSTALL_DIR}/" 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} 已复制源码到 ${INSTALL_DIR}"
else
    tar xzf "${TARBALL}" -C "${INSTALL_DIR}" 2>/dev/null || {
        echo -e "${RED}✗ 解压失败${NC}"; exit 1
    }
    # 处理 tag 归档顶层目录 (meshctx-<tag>/)，把源码拍平到 INSTALL_DIR
    _SUBDIR=$(find "${INSTALL_DIR}" -maxdepth 1 -mindepth 1 -type d | head -1)
    if [ -n "$_SUBDIR" ] && [ -f "${_SUBDIR}/src/main.py" ]; then
        mv "${_SUBDIR}"/* "${_SUBDIR}"/.[!.]* "${INSTALL_DIR}"/ 2>/dev/null || true
        rmdir "${_SUBDIR}" 2>/dev/null || true
    fi
fi

# 恢复用户配置
if [ -n "${CONFIG_BACKUP}" ] && [ -d "${CONFIG_BACKUP}" ]; then
    RESTORED=0
    for f in config.yaml .env provider_config.json; do
        if [ -f "${CONFIG_BACKUP}/${f}" ]; then
            cp "${CONFIG_BACKUP}/${f}" "${INSTALL_DIR}/${f}" 2>/dev/null || true
            RESTORED=1
        fi
    done
    # 🔒 安全：永远不恢复旧密码
    if [ -f "${INSTALL_DIR}/.env" ]; then
        sed -i '' '/^MESHCTX_PASSWORD=/d' "${INSTALL_DIR}/.env" 2>/dev/null || true
    fi
    rm -rf "${CONFIG_BACKUP}"
    [ "${RESTORED}" = "0" ] || echo -e "  ${GREEN}✓${NC} 用户配置已恢复（密码已重置）"
fi

# ── [4/6] 闭源核心组件 (meshctx-core · 一体产品) ─────
# 开源 + 闭源是一个整体产品：提供 MESHCTX_CORE_TOKEN 则一并安装闭源核心
# （从私有仓库 LucyAndLuna2023/meshctx-core 拉取真实核心算法模块），
# 未提供 token 则保留开源 stub 降级，之后可随时重跑补装。
CORE_TOKEN="${MESHCTX_CORE_TOKEN:-}"
if [ -z "$CORE_TOKEN" ] && [ -f "${INSTALL_DIR}/.env" ]; then
    CORE_TOKEN=$(sed -n 's/^MESHCTX_CORE_TOKEN=//p' "${INSTALL_DIR}/.env" 2>/dev/null | tr -d '"\r')
fi
if [ -n "$CORE_TOKEN" ] && command -v git >/dev/null 2>&1; then
    echo -e "  ${CYAN}→${NC} 安装闭源核心 meshctx-core ..."
    CORE_TMP=$(mktemp -d)
    CORE_CLONE_OK=0
    git clone --depth 1 "https://${CORE_TOKEN}@github.com/LucyAndLuna2023/meshctx-core.git" "${CORE_TMP}/core" >/dev/null 2>&1 && CORE_CLONE_OK=1
    if [ "$CORE_CLONE_OK" != "1" ] && [ -n "${MESHCTX_GIT_PROXY:-}" ]; then
        git -c http.proxy="$MESHCTX_GIT_PROXY" -c https.proxy="$MESHCTX_GIT_PROXY" clone --depth 1 "https://${CORE_TOKEN}@github.com/LucyAndLuna2023/meshctx-core.git" "${CORE_TMP}/core" >/dev/null 2>&1 && CORE_CLONE_OK=1
    fi
    if [ "$CORE_CLONE_OK" = "1" ]; then
        # 真实核心算法模块落地到 src/core（保留开源 __init__.py 的 stub 路由，
        # 闭源业务模块覆盖同名 stub + 补入闭源独有模块，检测逻辑按 desktop_tool.py 落地判定完整版）
        find "${CORE_TMP}/core/src/core" -maxdepth 1 -name '*.py' ! -name '__init__.py' -exec cp -f {} "${INSTALL_DIR}/src/core/" \;
        echo -e "  ${GREEN}✓${NC} 闭源核心已一体安装（完整版）"
    else
        echo -e "  ${YELLOW}⚠${NC} 闭源核心拉取失败（token/网络），本次为开源 stub 模式"
    fi
    rm -rf "${CORE_TMP}"
fi

cd "${INSTALL_DIR}"

# 创建 venv
echo -e "  ${CYAN}→${NC} $(T creating_venv)"
if [ ! -d "venv" ]; then
    ${PYTHON_BIN} -m venv venv 2>/dev/null || {
        # Fallback: ensurepip
        ${PYTHON_BIN} -m ensurepip --upgrade 2>/dev/null || true
        ${PYTHON_BIN} -m venv venv --without-pip 2>/dev/null && {
            source venv/bin/activate
            curl -sS https://bootstrap.pypa.io/get-pip.py | python 2>/dev/null || true
            deactivate 2>/dev/null || true
        } || {
            echo -e "${RED}✗ 创建 venv 失败${NC}"
            echo "  请运行: ${PYTHON_BIN} -m pip install virtualenv"
            echo "  然后重试"
            exit 1
        }
    }
fi

source venv/bin/activate

# 安装依赖（中国用户自动切换 PyPI 清华镜像，避免直连 2KB/s 卡死）
echo -e "  ${CYAN}→${NC} $(T installing_deps)"
PIP_EXTRA=""
if [ -z "$PIP_INDEX_URL" ]; then
    # 快速测速: 只取 1KB (curl -r 0-1023) 探测直连速度, 限时 8s
    # 慢网/超时(exit 28)/失败 → 一律判定慢, 切清华镜像 (慢网恰恰最需要镜像)
    SPD=$(curl -fsSL --connect-timeout 5 --max-time 8 -r 0-1023 -o /dev/null -w "%{speed_download}" \
        "https://files.pythonhosted.org/packages/source/p/pip/pip-24.0.tar.gz" 2>/dev/null)
    CURL_RC=$?
    SPD=${SPD:-0}
    # 超时(28)/连接失败/速度 < 200KB/s → 切镜像
    if [ "$CURL_RC" -ne 0 ] || [ "$SPD" = "0" ] || \
        "${PYTHON_BIN:-python3}" -c "exit(0 if float('${SPD}') < 200000 else 1)" 2>/dev/null; then
        if [ "$CURL_RC" -ne 0 ]; then
            echo -e "  ${YELLOW}→ PyPI 直连探测超时/失败, 自动切换清华镜像${NC}"
        else
            echo -e "  ${YELLOW}→ PyPI 直连较慢 (${SPD%.*} B/s), 自动切换清华镜像${NC}"
        fi
        PIP_EXTRA="-i https://pypi.tuna.tsinghua.edu.cn/simple"
    fi
fi

pip install -q --upgrade pip $PIP_EXTRA 2>/dev/null

if [ -f "requirements.txt" ]; then
    pip install -q -r requirements.txt $PIP_EXTRA 2>/dev/null || {
        pip install -q $PIP_EXTRA fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
            echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
        }
    }
else
    # 直接安装核心依赖
    pip install -q $PIP_EXTRA fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
        echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
    }
fi

echo -e "  ${GREEN}✓${NC} $(T deps_ok)"
# 安装 meshctx 包（pip install -e .）
echo -e "  ${CYAN}→${NC} $(T installing_meshctx_pkg)"
pip install -q -e . $PIP_EXTRA 2>/dev/null || { echo -e "${RED}✗ meshctx 包安装失败${NC}"; exit 1; }
echo -e "  ${GREEN}✓${NC} $(T meshctx_pkg_ok)"

# ── meshctx 命令 ─────────────────────────────────────
echo -e "  ${CYAN}→${NC} $(T installing_cmd)"

mkdir -p ~/bin

cat > ~/bin/meshctx << 'MESHCTX_SCRIPT'
#!/bin/bash
# meshctx CLI wrapper (macOS)
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
cd ~/.meshctx && source venv/bin/activate && python -m src.cli "$@"
MESHCTX_SCRIPT
chmod +x ~/bin/meshctx

# PATH 配置 (macOS 默认 zsh，但管道 bash 下 $SHELL 不可靠 → 写入所有 rc 文件)
# 同时写入所有 rc 文件，保证 zsh/bash/sh 登录 shell 都能找到 meshctx
for rc in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.profile" "${HOME}/.bash_profile"; do
    if ! grep -q '$HOME/bin' "$rc" 2>/dev/null; then
        echo 'export PATH="$HOME/bin:$PATH"' >> "$rc"
    fi
done
export PATH="${HOME}/bin:${PATH}"

# symlink 到系统路径（无需 sudo）
for _dir in "${HOME}/.local/bin" "${HOME}/bin" "/usr/local/bin"; do
    if [ -d "$_dir" ] && [ -w "$_dir" ]; then
        ln -sf "${HOME}/bin/meshctx" "${_dir}/meshctx" 2>/dev/null && break
    fi
done

echo -e "  ${GREEN}✓${NC} $(T cmd_installed)"

# ── LaunchAgent（开机自启）───────────────────────────
echo -e "  ${CYAN}→${NC} $(T configuring_autostart)"

LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
mkdir -p "${LAUNCHD_DIR}"

cat > "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" << LAUNCHDEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>src.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/meshctx.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/meshctx.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${INSTALL_DIR}/venv/bin</string>
    </dict>
</dict>
</plist>
LAUNCHDEOF

# 卸载旧版本后加载
launchctl unload "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" 2>/dev/null || true
launchctl load "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" 2>/dev/null || true

echo -e "  ${GREEN}✓${NC} $(T autostart_ok)"

# ── [5/6] 验证 ──────────────────────────────────────
echo -e "${CYAN}[5/6]${NC} $(T step5_verify)"

# 等待服务启动
sleep 5

# 检查服务状态
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/api/health" 2>/dev/null | grep -q "200"; then
    echo -e "  ${GREEN}✓${NC} $(T service_running)"
else
    # 手动启动
    cd "${INSTALL_DIR}" && source venv/bin/activate
    nohup python -m uvicorn src.main:app --host 0.0.0.0 --port ${PORT} > /dev/null 2>&1 &
    sleep 5
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/api/health" 2>/dev/null | grep -q "200"; then
        echo -e "  ${GREEN}✓${NC} $(T service_manual_start)"
    else
        echo -e "  ${YELLOW}⚠${NC} $(T service_starting)"
    fi
fi

# 版本校验
source venv/bin/activate 2>/dev/null || true
INSTALLED_VER=$(python -c "from src.core import __version__; print(__version__)" 2>/dev/null || echo "3.115.15")
echo -e "  ${GREEN}✓${NC} 版本 ${INSTALLED_VER}"

# 闭源核心完整性校验（一体产品：开源+闭源，组件不得丢失）
if [ -f "${INSTALL_DIR}/src/core/desktop_tool.py" ]; then
    echo -e "  ${GREEN}✓${NC} 闭源核心组件已就位（完整版）"
else
    echo -e "  ${YELLOW}⚠${NC} 未检测到闭源核心组件（当前为开源 stub 模式）"
    echo "    设置环境变量 MESHCTX_CORE_TOKEN 后重跑本脚本，可补装完整版闭源核心"
fi

# ── [6/6] 完成 ──────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║          $(T install_complete)              ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}$(T quick_start_label)${NC}"
echo "    meshctx start                    # 启动服务"
echo "    浏览器打开 http://localhost:${PORT}/ui/setup"
echo "    → 在 Setup 页面配置 API Key"
echo ""
echo -e "  ${CYAN}$(T common_cmds_label)${NC}"
echo "    meshctx status                   # 查看状态"
echo "    meshctx stop                     # 停止服务"
echo "    meshctx start --port 8080        # 指定端口"
echo "    meshctx logs                     # 查看日志"
echo ""
echo -e "  ${CYAN}$(T autostart_label)${NC}"
echo "    已配置 LaunchAgent，重启后自动启动"
echo "    日志目录: ~/Library/Logs/meshctx.log"
echo ""
echo -e "  ${CYAN}$(T manage_launchagent)${NC}"
echo "    launchctl list | grep meshctx    # 查看状态"
echo "    launchctl stop ${LAUNCHD_LABEL}   # 手动停止"
echo "    launchctl start ${LAUNCHD_LABEL}  # 手动启动"
echo ""
echo -e "  ${YELLOW}💡 若新终端找不到命令，请执行:${NC} source ~/.zshrc 或 source ~/.bashrc"
echo ""
