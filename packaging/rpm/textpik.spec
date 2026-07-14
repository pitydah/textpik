Name:           textpik
Version:        0.4.0
Release:        0.rc1%{?dist}
Summary:        Compact action bar for selected text
License:        GPL-3.0-or-later
URL:            https://github.com/pitydah/textpik
Source0:        %{url}/archive/refs/tags/v0.4.0-rc.1.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel python3-pip pyproject-rpm-macros
Requires:       python3-pyside6 python3-gobject at-spi2-core xdg-utils
Recommends:     wl-clipboard xdotool
Suggests:       python3-pyenchant hunspell-es

%description
TextPik shows context-aware actions next to selected text on Linux desktops.

%prep
%autosetup -n textpik-0.4.0-rc.1

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files textpik_core
install -Dm644 packaging/textpik.desktop %{buildroot}%{_datadir}/applications/textpik.desktop
install -Dm644 assets/app/textpik.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/textpik.svg
install -Dm644 packaging/io.github.pitydah.textpik.metainfo.xml %{buildroot}%{_metainfodir}/io.github.pitydah.textpik.metainfo.xml
mkdir -p %{buildroot}%{_datadir}/textpik
cp -a assets kwin %{buildroot}%{_datadir}/textpik/

%files -f %{pyproject_files}
%license LICENSE
%{_bindir}/textpik
%{python3_sitelib}/textpik.py
%{python3_sitelib}/__pycache__/textpik.cpython-*.pyc
%{_datadir}/applications/textpik.desktop
%{_datadir}/icons/hicolor/scalable/apps/textpik.svg
%{_metainfodir}/io.github.pitydah.textpik.metainfo.xml
%{_datadir}/textpik/
%{_docdir}/textpik/

%changelog
* Mon Jul 13 2026 TextPik contributors <pitydah@github.com> - 0.4.0-0.rc1
- First release candidate with crash fixes and intelligent selection sessions
