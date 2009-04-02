
import sets
import time
import datetime

import numpy

from graphtool.database.query_handler import results_parser, \
    complex_pivot_parser
from query_handler import gip_parser

class NMax(object):

    def __init__(self, n):
        self.data = numpy.zeros(n)

    def add_datum(self, val):
        argmin = self.data.argmin()
        self.data[argmin] = max(val, self.data[argmin])

    def get_max(self):
        return numpy.average(self.data)

class NMinMax(object):

    def __init__(self, n):
        self.data = numpy.zeros(n)

    def add_datum(self, val):
        argmin = self.data.argmin()
        self.data[argmin] = max(val, self.data[argmin])

    def get_max(self):
        return min(self.data)

def OIM_to_gratia_mapper(oim_vos, gratia_vos):
    """
    Maps the OIM VO names to Gratia VO Names
    Returns a map of oim to gratia and a map of gratia to oim.
    """
    oim_to_gratia = {}
    gratia_to_oim = {}
    print oim_vos
    print gratia_vos
    for oim_vo in oim_vos:
        oim_lower = oim_vo.lower()
        for gratia_vo in gratia_vos:
            gratia_lower = gratia_vo.lower()
            if gratia_lower.find(oim_lower) >= 0 or \
                    oim_lower.find(gratia_lower) >= 0:
                oim_to_gratia[oim_vo] = gratia_vo
                gratia_to_oim[gratia_vo] = oim_vo

    #for key, val in oim_to_gratia.items():
    #    print key, val
    return oim_to_gratia, gratia_to_oim

def HEP_classifier(vos, globals=globals()):
    """
    Returns all the VOs that are HEP VOs.
    """
    fields_of_science, _ = globals['RSVQueries'].field_of_science()
    oim_vos = [i[0] for i in fields_of_science]
    oim_to_gratia, gratia_to_oim = OIM_to_gratia_mapper(oim_vos, vos)
    hep_vos = []
    for vo in vos:
        is_hep = False
        oim_vo = gratia_to_oim.get(vo, None)
        for ov, science in fields_of_science:
             if ov == oim_vo and science == 'HEP':
                 hep_vos.append(vo)
    return hep_vos

def non_HEP_filter(sql_results, globals=globals(), **kw):
    """
    Removes results for HEP VOs.
    """
    results, md = results_parser(sql_results, globals=globals, **kw)
    hep_vos = HEP_classifier(results.keys(), globals=globals)
    print "HEP VOs"
    print "\n".join(hep_vos)
    filtered_results = {}
    for pivot, group in results.items():
        if pivot not in hep_vos:
            filtered_results[pivot] = group
    return filtered_results, md

precedence = {\
  'USLHC': 0,
  'HEP': 1,
  'Physics': 2,
  'Community Grid': 3,
  'Other': 4,
}
def science_classifier(sql_results, globals=globals(), default="Other", **kw):
    """
    Take in some VO-based metric and convert it to a field of science-based
    metric.  Uses the fact that the field of science is recorded by OIM.
    """
    results, md = results_parser(sql_results, globals=globals, **kw)
    fields_of_science, _ = globals['RSVQueries'].field_of_science()
    gratia_vos = results.keys()
    #print fields_of_science
    oim_vos = [i[0] for i in fields_of_science]
    oim_to_gratia, gratia_to_oim = OIM_to_gratia_mapper(oim_vos, gratia_vos)
    vo_to_science = {}
    for oim_vo, science_field in fields_of_science:
        current_science = vo_to_science.get(oim_vo, '')
        precedence_cur = precedence.get(current_science, 99)
        precedence_new = precedence.get(science_field)
        #print oim_vo, science_field, precedence_new, current_science, precedence_cur
        if precedence_new < precedence_cur:
            vo_to_science[oim_vo] = science_field
    #print "Gratia VO to Science"
    #for vo, science in vo_to_science.items():
    #    print vo, science
    filtered_results = {}
    for pivot, groups in results.items():
        if pivot in gratia_to_oim and gratia_to_oim[pivot] in vo_to_science:
            new_pivot = vo_to_science[gratia_to_oim[pivot]]
        else:
            #print "Unclassified VO:", pivot
            new_pivot = default
        if new_pivot not in filtered_results:
            filtered_results[new_pivot] = groups
        else:
            for group, val in groups.items():
                cur = filtered_results[new_pivot].get(group, 0)
                filtered_results[new_pivot][group] = cur + val
    if 'Physics' in filtered_results:
        filtered_results['non-HEP Physics'] = filtered_results['Physics']
        del filtered_results['Physics']
    return filtered_results, md

def site_size_parser(sql_results, globals=globals(), **kw):
    """
    Take in CPU hours information (# of wall hours per timespan per site)
    and convert it into the "size" of the site as a function of time.
    """
    print "in site size parser"
    results, md = results_parser(sql_results, globals=globals, **kw)
    span = kw['span']
    hours = span / 3600.
    sites = results.keys()
    new_results = {}
    all_intervals = sets.Set()
    for site in sites:
        intervals = results[site].keys()
        all_intervals.union_update(intervals)
    print len(all_intervals)
    all_intervals = list(all_intervals)
    all_intervals.sort()
    for site in sites:
        new_results[site] = {}
        mymax = NMax(2)
        for start in all_intervals:
            avg_cpus = results[site].get(start, 0) / hours
            mymax.add_datum(avg_cpus)
            new_results[site][start] = mymax.get_max()
    return new_results, md

def site_size_parser2(sql_results, globals=globals(), **kw):
    """
    Take pivot-group information about site size, and summarize it into 1D info
    suitable for a pie chart.
    """
    data, md = site_size_parser(sql_results, globals, **kw)
    md['kind'] = 'pivot'
    new_data = {}
    for site, values in data.items():
        new_data[site] = max(values.values())
    return new_data, md

LHC_SC = 'LHC S&C'
LHC_REL = 'LHC Related'
OTHER = 'Other Grid'
LHC_VOS = ['ATLAS', 'CMS']

def resource_classifier(globals=globals(), **kw):
    perc, md = globals['RSVQueries'].ownership()
    feds, _ = globals['RSVQueries'].resource_to_federation()
    wlcg_resources = feds.keys()
    resources, _ = globals['RSVQueries'].resources()
    resources = resources.keys()

    results = {}
    for resource in resources:
        for pivot, info in perc:
            vo, percent = info
            if pivot != resource:
                continue
            if vo in LHC_VOS and resource in wlcg_resources:
                classification = LHC_SC
            elif vo in LHC_VOS:
                classification = LHC_REL
            else:
                classification = OTHER
            resource_set = results.setdefault(resource, sets.Set())
            resource_set.add((vo, percent, classification))
    #for resource, set in results.items():
    #    print resource, set
    return results, md

def size_classifier(sql_results, globals=globals(), **kw):
    """
    Taking the outputs of the site_size_parser2, return information about the
    site classification (LHC S&C, LHC related, or other) and their sizes
    """
    data, md = site_size_parser2(sql_results, globals=globals, **kw)
    resource_info, _ = resource_classifier(globals=globals, **kw)
    results = {LHC_SC: 0, LHC_REL: 0, OTHER: 0}
    for resource, size in data.items():
        if resource not in resource_info:
            results[OTHER] += size
            continue
        for vo, percent, classification in resource_info[resource]:
            results[classification] += int(percent)/100.0*size
    return results, md

def site_resource_classifier(sql_results, globals=globals(), **kw):
    """
    Similar to site_resource_classifier: from the input data, return the
    size grouped by classification and site name.
    """
    data, md = site_size_parser2(sql_results, globals=globals, **kw)
    md['kind'] = 'pivot-group'
    resource_info, _ = resource_classifier(globals=globals, **kw)
    results = {LHC_SC: {}, LHC_REL: {}, OTHER: {}}
    for resource, size in data.items():
        if resource not in resource_info:
            current = results[OTHER].get(resource, 0)
            results[OTHER][resource] = size + current
            continue
        for vo, percent, classification in resource_info[resource]:
            current = results[classification].get(resource, 0)
            results[classification][resource] = int(percent)/100.0*size + \
                current
    return results, md


def gip_size_parser(sql_results, globals=globals(), **kw):
    """
    Take in GIP batch system sizes and convert it into "maximum reported size"
    data.
    """
    results, md = gip_parser(sql_results, globals=globals, **kw)
    sites = results.keys()
    new_results = {}
    all_intervals = sets.Set()
    for site in sites:
        intervals = results[site].keys()
        all_intervals.union_update(intervals)
    all_intervals = list(all_intervals)
    all_intervals.sort()
    for site in sites:
        new_results[site] = {}
        mymax = NMinMax(3)
        for start in all_intervals:
            avg_cpus = results[site].get(start, 0)
            mymax.add_datum(avg_cpus)
            new_results[site][start] = mymax.get_max()
    return new_results, md

def gip_size_parser2(sql_results, globals=globals(), **kw):
    """
    Take pivot-group information about GIP size, and summarize it into 1D info
    suitable for a pie chart.
    """
    data, md = gip_size_parser(sql_results, globals, **kw)
    md['kind'] = 'pivot'
    new_data = {}
    for site, values in data.items():
        new_data[site] = max(values.values())
    return new_data, md

def gip_subcluster_score(sql_results, globals=globals(), **kw):
    """
    Take in GIP batch system sizes and convert it into "maximum reported size"
    data.
    """
    results, md = gip_parser(sql_results, globals=globals, **kw)
    sites = results.keys()
    new_results = {}
    all_intervals = sets.Set()
    for site in sites:
        intervals = results[site].keys()
        all_intervals.union_update(intervals)
    all_intervals = list(all_intervals)
    all_intervals.sort()
    for site in sites:
        new_results[site] = {}
        mymax = NMax(3)
        for start in all_intervals:
            avg_cpus = results[site].get(start, 0)
            mymax.add_datum(avg_cpus)
            new_results[site][start] = mymax.get_max()
    return new_results, md


class NormalizationConstants:

    def __init__(self, gip_queries, starttime=None, endtime=None, span=None):
        kw = {}
        if starttime:
            kw['starttime'] = starttime
        if endtime:
            kw['endtime'] = endtime
        if span:
            kw['span'] = span
        self.ksi2k, _ = gip_queries.subcluster_score_ts(**kw)
        ksi2k_avg, _ = gip_queries.subcluster_score_ts2(**kw)
        self.ksi2k_avg = ksi2k_avg['Nebraska']
 
    def __getitem__(self, site):
        if site in self.ksi2k and len(self.ksi2k[site]) > 0:
            return sum(self.ksi2k[site].values())/len(self.ksi2k[site])
        else:
            return sum(self.ksi2k_avg.values())/len(self.ksi2k_avg)

    def getNorm(self, time, site):
        if site in self.ksi2k and time in self.ksi2k[site]:
            return self.ksi2k[site][time]
        elif time in self.ksi2k_avg:
            return self.ksi2k_avg[time]
        else:
            return self[site]
            

def osg_size(sql_results, globals=globals(), **kw):
    """
    Calculate the OSG's size in terms of utilized CPUs, accessible CPUs, and
    total CPUs..
    """
    if 'normalize' in kw and kw['normalize'].lower().find('t') >= 0:
        normalize = True
    else:
        normalize = False
    utilized_results, md = results_parser(sql_results, globals=globals, **kw)
    accessible_results, _ = globals['GratiaBarQueries'].osg_avail_size(span=7*86400,
        starttime=time.time()-7*86400*52)
    total_results, _ = globals['GIPQueries'].gip_site_size(span=7*86400,
        starttime=time.time()-7*86400*52, max_size=20000)
    ksi2k_results, _ = globals['GIPQueries'].subcluster_score_ts()
    ksi2k_results2, _ = globals['GIPQueries'].subcluster_score_ts2()
    ksi2k_results2 = ksi2k_results2['Nebraska']
    sites = utilized_results.keys()
    new_results = {}
    all_intervals = sets.Set()
    for site in sites:
        intervals = utilized_results[site].keys()
        all_intervals.union_update(intervals)
    all_intervals = list(all_intervals)
    all_intervals.sort()
    total_utilized_results = {}
    total_accessible_results = {}
    total_total_results = {}
    final_results = {'Used': {}, 'Accessible, but not Used': {},
        'In OSG, but not Accessible': {}}
    may_1 = time.mktime((2008, 05, 01, 0, 0, 0, 0, 0, 0))
    avg_ksi2k_results = {}
    ksi2k_min = min(1.7, ksi2k_results2.values())
    ksi2k_max = ksi2k_min
    for interval in all_intervals:
        ksi2k_max = max(ksi2k_results2.get(interval, ksi2k_min), ksi2k_max)
        avg_ksi2k_results[interval] = ksi2k_max
    for interval in all_intervals:
        print interval, avg_ksi2k_results[interval]
        cumulative = 0
        for site, vals in utilized_results.items():
            if site not in ksi2k_results:
                ksi2k = avg_ksi2k_results[interval]
            elif interval not in ksi2k_results[site]:
                ksi2k = min(ksi2k_results[site].values(),
                    avg_ksi2k_results[interval])
            else:
                ksi2k = ksi2k_results[site][interval]
            if normalize:
                cumulative += vals.get(interval, 0) * ksi2k
            else:
                cumulative += vals.get(interval, 0)
        total_utilized_results[interval] = cumulative
        cumulative2 = 0
        for site, vals in accessible_results.items():
            if site not in ksi2k_results:
                ksi2k = avg_ksi2k_results[interval]
            elif interval not in ksi2k_results[site]:
                ksi2k = min(ksi2k_results[site].values(), 
                    avg_ksi2k_results[interval])
            else:
                ksi2k = ksi2k_results[site][interval]
            if normalize:
                cumulative2 += vals.get(interval, 0) * ksi2k
            else:
                cumulative2 += vals.get(interval, 0)
        total_accessible_results[interval] = cumulative2
        cumulative3 = 0
        for site, vals in total_results.items():
            if site not in ksi2k_results:
                ksi2k = avg_ksi2k_results[interval]
            elif interval not in ksi2k_results[site]:
                ksi2k = min(ksi2k_results[site].values(), 
                    avg_ksi2k_results[interval])
            else:
                ksi2k = ksi2k_results[site][interval]
            if normalize:
                cumulative3 += vals.get(interval, 0) * ksi2k
            else:
                cumulative3 += vals.get(interval, 0)
        total_total_results[interval] = cumulative3

        if interval < may_1:
            continue
        final_results['Used'][interval] = cumulative
        final_results['Accessible, but not Used'][interval] = cumulative2 - \
            cumulative
        final_results['In OSG, but not Accessible'][interval] = cumulative3 - \
            cumulative2
    return final_results, md

