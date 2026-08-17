%global __os_install_post %{nil}

Name:           purplefin-bitwarden-cli
Version:        %{cli_version}
Release:        1
Summary:        Official Bitwarden command-line client packaged for Purplefin
License:        GPL-3.0-only AND LicenseRef-Bitwarden-SDK
URL:            https://bitwarden.com/help/cli/
Source0:        bw
Source1:        bitwarden-cli.provenance
BuildArch:      x86_64
Provides:       bitwarden-cli = %{version}-%{release}

%description
Bitwarden's official native Linux command-line client, wrapped without binary
modification in an RPM for Purplefin image ownership and lifecycle tracking.

%prep

%build

%install
install -D -m 0755 %{SOURCE0} %{buildroot}%{_bindir}/bw
install -D -m 0644 %{SOURCE1} %{buildroot}%{_docdir}/%{name}/provenance

%files
%{_bindir}/bw
%doc %{_docdir}/%{name}/provenance

%changelog
* Sat Jul 11 2026 Purplefin <purplefin@localhost> - %{version}-1
- Wrap Bitwarden's official native CLI without modifying its binary payload.
