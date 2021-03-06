
import re
import sys
import time
import types
import urllib
import urllib2
import calendar
import datetime
import json
from xml.dom.minidom import parse
from ConfigParser import ConfigParser

import cherrypy 
from pkg_resources import resource_stream

from graphtool.base.xml_config import XmlConfig
from auth import Authenticate
from gratia.gip.cpu_normalizations import get_cpu_normalizations
from wlcg_json_data import WLCGWebUtil

def gratia_interval(year, month):
    info = {}
    info['starttime'] = datetime.datetime(year, month, 1, 0, 0, 0)
    last_day = calendar.monthrange(year, month)[1]
    info['endtime'] = datetime.datetime(year, month, last_day, 23, 59, 59)
    return info

class WLCGReporter(Authenticate):

    def add_effort(self, site_info, site, VOMoU, apel_data, gratia_data, \
            gratia_cpu_data):
        for key in ['wlcgNormWCT', 'voNormWCT', 'totalNormWCT', 'wlcgNormCPU',\
                'voNormCPU', 'totalNormCPU']:
            if key not in site_info:
                site_info[key] = 0
        norm = None
        for row in apel_data:
            if str(row['ExecutingSite']) != site:
                continue
            norm = float(row['HS06Factor'])
            if row['LCGUserVO'].find(VOMoU) >= 0:
                site_info['voNormWCT'] += int(row['HS06_WCT'])
                site_info['voNormCPU'] += int(row['HS06_CPU'])
            site_info['wlcgNormWCT'] += int(row['HS06_WCT'])
            site_info['wlcgNormCPU'] += int(row['HS06_CPU'])
            site_info['norm'] = norm
        if norm:
            site_info['totalNormWCT'] += int(norm * gratia_data.get(site, 0))
            site_info['totalNormCPU'] += int(norm * gratia_cpu_data.get(site,0))
               
    def getText(self, nodelist):
	    rc = ""
	    for node in nodelist:
	        if node.nodeType == node.TEXT_NODE:
	            rc = rc + node.data
	    return rc

    def getcpuinfodictionary(self):
	urlcpuinfo='http://myosg.grid.iu.edu/misccpuinfo/xml?count_sg_1&count_active=on&count_enabled=on&datasource=cpuinfo'
	xmldoc = urllib2.urlopen(urlcpuinfo)
	dom = parse(xmldoc)
	hepspecCpuDict = {}
	normconstCpuDict = {}
	for rowDom in dom.getElementsByTagName('CPUInfo'):
	    cpuname=self.getText((rowDom.getElementsByTagName("Name")[0]).childNodes).upper().replace(' ', '')
	    hepspec=self.getText((rowDom.getElementsByTagName("HEPSPEC")[0]).childNodes)
            normconstant = self.getText((rowDom.getElementsByTagName("NormalizationConstant")[0]).childNodes) 
	    hepspecCpuDict[cpuname]=hepspec
	    normconstCpuDict[cpuname]=normconstant
        return hepspecCpuDict,normconstCpuDict
 


    def make_pledge_format(self, year, month):
	atlas_pledge, cms_pledge,atlas_dict, cms_dict, alice_pledge, alice_dict=WLCGWebUtil().wlcg_pledges(month, year)
        results = []
        for fed, info in atlas_pledge.items():
             for site in info['site_names']:
                 results.append((fed, info['pledge'], info['pledge'], 'atlas',
                     '', fed, site))
        for fed, info in cms_pledge.items():
             for site in info['site_names']:
                 results.append((fed, info['pledge'], info['pledge'], 'cms',
                     '', fed, site))
        for fed, info in alice_pledge.items():
             for site in info['site_names']:
                 results.append((fed, info['pledge'], info['pledge'], 'alice',
                     '', fed, site))
        return results

    def t2_pledges(self, apel_data, year, month):
        # Get Gratia data
        gratia_data = self.globals['GratiaPieQueries'].osg_facility_hours( \
            **gratia_interval(year, month))[0]
        gratia_cpu_data = self.globals['GratiaPieQueries'].\
            osg_facility_cpu_hours( **gratia_interval(year, month))[0]
        pledge_info = {}
        last_day = calendar.monthrange(year, month)[1]
        # Pop off the headers
        for line in self.make_pledge_format(year, month):
            fed, pledge07, pledge08, VOMoU, VOaddl, accounting, site = line

            if accounting != '':
                my_accounting = accounting
            if pledge07 != '':
                my_pledge07 = pledge07
            if pledge08 != '':
                my_pledge08 = pledge08
            site = site.replace("Uflorida", "UFlorida")
            vo_info = pledge_info.get(VOMoU, {})
            pledge_info[VOMoU] = vo_info
            site_info = vo_info.get(my_accounting, {})
            vo_info[my_accounting] = site_info
            site_info['pledge07'] = my_pledge07
            site_info['pledge08'] = my_pledge08
            if (year >= 2008 and month >= 4) or year > 2008:
                site_info['pledge'] = my_pledge08
            else:
                site_info['pledge'] = my_pledge07
            site_info['efficiency'] = .67
            site_info['days_in_month'] = last_day
            self.add_effort(site_info, site, VOMoU, apel_data, gratia_data, \
                gratia_cpu_data)
            sites = site_info.get('sites', [])
            site_info['sites'] = sites
            if site not in sites:
                sites.append(site)
        for vo, vo_info in pledge_info.items():
            refined_vo_info = {}
            for site, site_info in vo_info.items():
                if site_info['totalNormWCT'] != 0:
                    refined_vo_info[site] = site_info
            pledge_info[vo] = refined_vo_info
        return pledge_info


    def site_normalization(self):
        data = {}
        apel_data, reporting_time = self.get_apel_data()
        # Determine all the WLCG sites:
        wlcg_sites = []
        for row in apel_data:
            if row['ExecutingSite'] not in wlcg_sites:
                wlcg_sites.append(row['ExecutingSite'])
        #print wlcg_sites
        data['subclusters'], data['time_list'] = self.gratia_data()

        # Determine site normalization:
        site_norm = {}
        data['site_norm'] = site_norm
        tmp_norm = {}
        report_time = None
        for key, val in data['subclusters'].items():
            if report_time == None:
                report_time = val[0]
            site = key[0]
            if site not in wlcg_sites:
                #print >> sys.stderr, "Skipping site:", site
                if site.startswith('BNL-ATLAS'):
                    site = 'BNL_ATLAS_1'
                elif site.startswith('USCMS-FNAL-WC1'):
                    site = 'USCMS-FNAL-WC1-CE'
                else:
                    #print site
                    continue
            info = tmp_norm.get(site, [])
            tmp_norm[site] = info
            info.append((val[2], val[3]))
        data['gip_report_time'] = report_time
        for site, info in tmp_norm.items():
            total_cores = 0
            total_si2k = 0
            for cores, si2k in info:
                total_cores += cores
                total_si2k += si2k*cores
            gipnorm = int(total_si2k / total_cores)
            site_norm[site] = gipnorm
            #print site

        #Output data:
        strng = '# GIP Report time: %s\n' % report_time
        for site, info in site_norm.items():
            strng += '%s %i\n' % (site, info)
        cherrypy.response.headers['Content-Type'] = 'text/plain'
        return strng
    site_normalization.exposed = True

    def gratia_data(self, timestamp=None):
        if timestamp==None:
            subclusters = self.globals['GratiaStatusQueries'].\
                status_subcluster_latest()[0]
        else:
            subclusters = self.globals['GratiaStatusQueries'].\
                status_subcluster_latest(endtime=timestamp)[0]
        time_list = self.globals['GratiaStatusQueries'].\
            status_subcluster_times()
        return subclusters, time_list

    def get_apel_data_since201203(self, month, year):
        apel_url = self.metadata.get('apel_url', 'http://gr7x3.fnal.gov:8880/gratia-data/interfaces/apel-lcg/%i-%02i.summary.dat'\
            % (year, month))
        usock = urllib2.urlopen(apel_url)
        data = usock.read()
        usock.close()
        apel_data = []
        datafields = []
        numcells=11
        report_time = None
        for i in range(numcells):
            datafields.append(0)
        datafields[0]="ExecutingSite"
        datafields[1]="HS06Factor"
        datafields[2]="LCGUserVO"
        datafields[3]="Njobs"
        datafields[4]="SumCPU"
        datafields[5]="SumWCT"
        datafields[6]="HS06_CPU"
        datafields[7]="HS06_WCT"
        datafields[8]="RecordStart"
        datafields[9]="RecordEnd"
        datafields[10]="MeasurementDate"
        linesrec=data.split('\n')
        for line in linesrec:
            eachfield=line.split('\t')
            count=0
            info = {}
            for field in eachfield:
                if(field.strip() == ""):
                    continue
                if(count<numcells):
                    info[datafields[count]]=field
                if count<numcells and datafields[count] == 'MeasurementDate' and report_time == None:
                    report_time = field
                count=count+1
            if(not info):
                continue
            info['month']=month
            info['year']=year
            apel_data.append(info)
        return apel_data, report_time

    def get_apel_data(self, year=datetime.datetime.now().year, month=datetime.datetime.now().month):
        year = int(year)
        month = int(month)
        if(year >=2012 and month >= 3):
            return self.get_apel_data_since201203(month, year)
        apel_url = self.metadata.get('apel_url', 'http://gratia-osg-prod-reports.opensciencegrid.org/gratia-data/interfaces/apel-lcg/%i-%02i.HS06_OSG_DATA.xml'\
            % (year, month))
        xmldoc = urllib2.urlopen(apel_url)
        dom = parse(xmldoc)
        apel_data = []
        report_time = None
        for rowDom in dom.getElementsByTagName('row'):
            info = {}
            for field in rowDom.getElementsByTagName('field'):
                name = str(field.getAttribute('name'))
                if len(name) == 0:
                    continue
                val = str(field.firstChild.data)
                info[name] = val
                if name == 'MeasurementDate' and report_time == None:
                    report_time = val
            if len(info) == 0:
                for child in rowDom.childNodes:
                    name = str(child.nodeName)
                    if not name or len(name) == 0:
                        continue
                    if child.nodeType == child.TEXT_NODE:
                        continue
                    val = str(child.firstChild.data)
                    info[name] = val
                    if name == 'MeasurementDate' and report_time == None:
                        report_time = val
            apel_data.append(info)
        return apel_data, report_time


    def apel_data(self, gip_time=None, year=datetime.datetime.now().year, 
            month=datetime.datetime.now().month, **kw):
        data = dict(kw)
        self.user_auth(data)
        self.user_roles(data)
        year = int(year)
        month = int(month)
        try:
            apel_data, report_time = self.get_apel_data(year, month)
            data['error'] = False
        except (KeyboardInterrupt, SystemExit):
            raise 
        except Exception, e:
            print >> sys.stderr, "Exception occurred while APEL data: %s" % str(e)
            data['title'] = "WLCG Reporting Info Error."
            data['error'] = True
            data['error_message'] = 'An error occurred when retrieving the data.'
            raise e
            return data
        data['apel'] = apel_data
        data['year'] = year
        data['month'] = month 
        data['month_name'] = calendar.month_name[month]
        data['report_time'] = report_time
        
        def key_sorter(key1, key2):
            if key1 < key2:
                return -1
            if key1 == key2:
                return 0
            return 1
        data['key_sorter'] = key_sorter
        apel_data.sort(key_sorter)
        # Add in the GIP data
        if gip_time == None:
            time_info = gratia_interval(year, month)
            data['subclusters'], data['time_list'] = self.gratia_data( \
                timestamp=time_info['endtime'])

        # Determine all the WLCG sites:
        wlcg_sites = []
        wlcg_norm = {}
        data['wlcg_sites'] = wlcg_sites
        for row in apel_data:
            if row['ExecutingSite'] not in wlcg_sites:
                wlcg_sites.append(row['ExecutingSite'])
                wlcg_norm[row['ExecutingSite']] = row['HS06Factor']


        # replace with hepspec numbers from  non-WLCG sites from CPUInfo.
        new_subclusters = {}
	hepspecCpuDict,normconstCpuDict = self.getcpuinfodictionary()
        for key, val in data['subclusters'].items():
	    cpukey=val[1].upper().replace(' ', '')
	    valcopy=[val[0],val[1],val[2],val[3],val[4],'']
	    try:
	            if float(hepspecCpuDict[cpukey]) > 0:
			valcopy[3]=(hepspecCpuDict[cpukey])
		    else:
			valcopy[3]=str(float(val[3])*4 / 1000)
			valcopy[5]='*'
	    except:
		valcopy[3]=str(float(val[3])*4 / 1000)
		valcopy[5]='*'

            new_subclusters[key] = valcopy
            #print key, val, '----------'
        data['subclusters'] = new_subclusters


        # Determine site normalization:
        site_norm = {}
        data['site_norm'] = site_norm
        tmp_norm = {}
        report_time = None
        for key, val in data['subclusters'].items():
            if report_time == None:
                report_time = val[0]
            site = key[0]
            if site not in wlcg_sites:
                continue
            info = tmp_norm.get(site, [])
            tmp_norm[site] = info
            info.append((val[2], val[3]))
        data['gip_report_time'] = report_time
        for site, info in tmp_norm.items():
            total_cores = 0
            total_si2k = 0
            for cores, si2k in info:
                total_cores += cores
                total_si2k += float(si2k)*cores
            gipnorm = float(int((float(total_si2k) / total_cores)*100))/100
            wlcgnorm = float(wlcg_norm[site])
            diff = int((gipnorm - wlcgnorm)/wlcgnorm * 100)
            site_norm[site] = (gipnorm, wlcgnorm, diff, int((4*total_si2k)/1000.))#convert to HEPSPEC,

        # Remove non-WLCG sites from the GIP data.
        new_subclusters = {}
        for key, val in data['subclusters'].items():
            if key[0] in wlcg_sites:
                new_subclusters[key] = val
                #print key, val
        data['subclusters'] = new_subclusters


        # Add in the pledge data
        data['pledge'] = self.t2_pledges(apel_data, year, month)
       
        # Determine site summary table.  Shows number of subclusters,
        # site name, and WLCG accounting name
        summary = {}
        for site in wlcg_sites:
            sum_info = summary.get(site, {})
            summary[site] = sum_info
            for key, val in data['subclusters'].items():
                 if key[0] == site:
                     num_subclusters = sum_info.get('subclusters', 0)
                     sum_info['subclusters'] = num_subclusters + 1
            for vo_key, vo_val in data['pledge'].items():
                for key, val in vo_val.items():
                    if site in val['sites']:
                        sum_info['accounting'] = key
                        if 'actual' not in val:
                            val['actual'] = 0
                        val['actual'] += site_norm.get(site, (0, 0, 0, 0))[3]
            if 'subclusters' not in sum_info:
                sum_info['subclusters'] = 0
            if 'accounting' not in sum_info:
                sum_info['accounting'] = "UNKNOWN"
        data['summary'] = summary

        data['title'] = "Reported WLCG data for %s %i" % \
            (calendar.month_name[month], year)
        if year >= 2008 and month >= 4:
            data['pledge_year'] = '2008'
        else:
            data['pledge_year'] = '2007'

        # Site availability hours
        rsv_data = self.get_rsv_data(apel_data, year, month)
        avail_data, act_avail_data, full_data, errors =  \
            self.get_ksi2k_availability(year, \
            month, apel_data, data['pledge'], rsv_data)
        data['act_avail'] = act_avail_data
        data['avail'] = avail_data
        data['availability'] = full_data
        #print data['availability']['Nebraska']
        return data

    def pledge_table(self, year=datetime.datetime.now().year, \
            month=datetime.datetime.now().month):
        month = int(month)
        year = int(year)
        apel_data, report_time = self.get_apel_data(year, month)
        pledges = self.t2_pledges(apel_data, year, month)
        cherrypy.response.headers['Content-Type'] = 'text/plain'
        info = {"report_time": report_time, "apel_data": apel_data,
            "pledges": pledges}
        return str(info)
    pledge_table.exposed = True

    def get_wlcg_sites(self, apel_data):
        wlcg_sites = []
        for row in apel_data:
            if row['ExecutingSite'] not in wlcg_sites:
                wlcg_sites.append(row['ExecutingSite'])
        return wlcg_sites

    def stringToDatetime(self, s):
        t_tuple = time.strptime(s, '%Y-%m-%d %H:%M:%S')
        return datetime.datetime(*t_tuple[:6])

    def get_rsv_data(self, apel_data, 
            year=datetime.datetime.now().year, \
            month=datetime.datetime.now().month, **kw):
        wlcg_sites = self.get_wlcg_sites(apel_data)
        daterange = gratia_interval(year, month)
        cur = daterange['starttime']
        end = min(daterange['endtime'], datetime.datetime.today())
        #data, _ = self.globals['RSVQueries'].rsv_reliability_daily( \
        #    starttime=cur, endtime=end)
        data = {}
        #site_map, _ = self.globals['GIPQueries'].site_info()
        site_map = {}
        new_data = {}
        try:
            one_key = data.keys()[0]
        except:
            return {}
        default_vals = [(i, 0.0) for i in data[one_key]]
        for site in wlcg_sites:
            new_data[site] = dict(default_vals)
        for key, val in data.items():
            if key not in site_map:
                continue
            new_data[site_map[key]] = val
        return new_data

    def parse_ownership(self, data, vo):
        r = re.compile("(\w+):([0-9]+)")
        m = r.findall(data)
        if m == None:
            raise Exception("Unable to determine %s ownership: %s." % \
                (vo, data))
        for grouping in m:
            sponsor, perc = grouping
            if sponsor.lower().find(vo) >= 0:
                return float(perc)/100.
        raise Exception("Unable to determine %s ownership: %s." % (vo, data))

    def _avg(self, values):
        myvals = [i for i in values if i > 0]
        try:
            return sum(myvals) / float(len(myvals))
        except:
            return 0

    def get_ksi2k_availability(self, year, month, apel_data, pledge_data, \
            rsv_data):
        info = gratia_interval(year, month)
        #print info
        gip_data, dummy = self.globals['GratiaStatusQueries'].status_subcluster_interval(**info)
        cur = info['starttime']
        end = min(info['endtime'], datetime.datetime.today())
        wlcg_sites = self.get_wlcg_sites(apel_data)
        data = {}
        size_data = {}
        gip_smry = {}
        oneday = datetime.timedelta(1, 0)
        errors = {}
        site_map = {}
        vo_ownership = {}
        for act_site, val in pledge_data['cms'].items():
            if 'sites' in val:
                site_map[act_site] = val['sites']
        for act_site, val in pledge_data['atlas'].items():
            if 'sites' in val:
                site_map[act_site] = val['sites']
        for act_site, val in pledge_data['alice'].items():
            if 'sites' in val:
                site_map[act_site] = val['sites']
        wlcg_act_sites = site_map.keys()
        for site in wlcg_sites:
            data[site] = {}
            size_data[site] = {}
            gip_smry[site] = {}
            if site not in rsv_data:
                errors[site] = "RSV data not available.  "
            else:
                errors[site] = ""
            vo_ownership[site] = "'(Unknown) '"
        while cur <= end:
            for site in wlcg_sites:
                gip_smry[site][cur] = 0
            cur += oneday
        for key, val in gip_data.items():
            #print key
            site = key[0]
            try:
                date = datetime.datetime(*time.strptime(str(key[3]), '%Y-%m-%d')[:3])
            except:
                raise
                raise Exception("Invalid date: %s" % key[3])
            if site not in wlcg_sites:
                continue
            pledge_vo = None
            for act_site, sites in site_map.items():
                if site in sites:
                    if act_site in pledge_data['atlas']:
                        pledge_vo = 'atlas'
                    elif act_site in pledge_data['alice']:
                        pledge_vo = 'alice'
                    else:
                        pledge_vo = 'cms'
            if pledge_vo == None:
                if site in errors and errors[site].find("site ownership") < 0:
                    errors[site] += "Unable to determine site ownership.  "
                continue
            try:
                ownership_perc = self.parse_ownership(val[3], \
                    pledge_vo)
            except:
                #raise
                if site in errors and errors[site].find("site ownership") < 0:
                    errors[site] += "Unable to determine site ownership.  "
                continue
            #print "*", site, "*", date, ownership_perc, val[1], val[2]
            gip_smry[site][date] += ownership_perc*val[1]*val[2]/float(1000.)
            vo_ownership[site] = str(int(100*ownership_perc))
        for site in wlcg_sites:
            #pledge_val = pledge_data['atlas'].get(site, {}).get('pledge', 0) +\
            #    pledge_data['cms'].get(site, {}).get('pledge', 0)
            if site not in gip_smry:
                errors[site] += "GIP data not available."
                continue
            #if pledge_val == 0:
            #    errors[site] += "Pledge data unavailable for %s.  " % site
            #    continue
            #gip_val = max(gip_smry[site].values())
            #if abs(gip_val-pledge_val)/float(pledge_val) > .5:
            #    errors[site] += "Suspect GIP data."
        cur = info['starttime']
        #print gip_smry
        while cur <= end:
            for site in wlcg_sites:
                gip_val = gip_smry.get(site, {})
                val = gip_val.get(cur, self._avg(gip_val.values()))
                if val == 0:
                    val = self._avg(gip_val.values())
                #print "Site", site, "Date", cur, "RSV data", rsv_data.get(site, {}).get(cur, 0), "GIP val", gip_val.get(cur, self._avg(gip_val.values()))
                data[site][cur] = rsv_data.get(site, {}).get(cur, 0) * val
                size_data[site][cur] = val
            cur += oneday
        act_data = {}
        for act_site in wlcg_act_sites:
            act_data[act_site] = 0
        for act_site, sites in site_map.items():
            for site in sites:
                if site in data:
                    act_data[act_site] += int(24*sum(data[site].values()))
        full_data = {}
        for site in wlcg_sites:
            full_data[site] = {}
            full_data[site]['rsv'] = int(100*self._avg(rsv_data.get(site, \
                {}).values()))
            full_data[site]['size'] = int(self._avg(size_data.get(site, \
                {}).values()))
            full_data[site]['ownership'] = vo_ownership[site]
            full_data[site]['availability'] = int(24*sum(data[site].values()))
        return data, act_data, full_data, errors

