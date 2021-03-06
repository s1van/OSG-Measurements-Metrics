Name: gratiagraph-monitor-rpm          
Version: 1.0        
Release: 2
Summary: Gratia Graph Monitor RPMs        

Group: Development/System          
License: GPL        
URL: http://hcc.unl.edu/ 
Source: gratiagraph-monitor.tar      
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}
BuildArch: noarch

%description
Gratia Graph Monitor RPMs

%install
rm -rf $RPM_BUILD_ROOT
tar -xvf $RPM_SOURCE_DIR/gratiagraph-monitor.tar
mkdir -p $RPM_BUILD_ROOT/%{_sysconfdir}/cron.d/
mkdir -p $RPM_BUILD_ROOT/%{_sbindir}/
cp gratiagraph-monitor/gratiagraph-monitor.cron $RPM_BUILD_ROOT/%{_sysconfdir}/cron.d/
cp gratiagraph-monitor/gratiagraph-monitor.sh $RPM_BUILD_ROOT/%{_sbindir}/

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)
%{_sysconfdir}/cron.d/gratiagraph-monitor.cron
%{_sbindir}/gratiagraph-monitor.sh
%doc


%changelog
* Tue Aug 16 2011  Ashu Guru <aguru2@unl.edu> 1.02
- Logs written to stdout
* Mon Jun 13 2011  Ashu Guru <aguru2@unl.edu> 1.01
- Initial version of the package

