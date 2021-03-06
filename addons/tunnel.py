#!/usr/bin/python
#
# Maximilian Wilhelm <max@rfc2324.org>
#  --  Mon 10 Oct 2016 10:53:13 PM CEST
#

from ifupdown.iface import *
from ifupdownaddons.modulebase import moduleBase
from ifupdownaddons.iproute2 import iproute2
from ifupdown.netlink import netlink
import ifupdown.ifupdownflags as ifupdownflags
import logging

#
# TODO: Add checks for ipip tunnels.
#
class tunnel (moduleBase):
    _modinfo = { 'mhelp' : 'create/configure GRE/IPIP/SIT and GRETAP tunnel interfaces',
                 'attrs' : {
                   'mode' :
                        { 'help' : 'type of tunnel as in \'ip link\' command.',
                          'validvals' : ['gre', 'gretap', 'ipip', 'sit', 'vti', 'ip6gre', 'ipip6', 'ip6ip6', 'vti6'],
                          'required' : True,
                          'example' : ['mode gre']},
                   'local' :
                        { 'help' : 'IP of local tunnel endpoint',
                          'validvals' : ['<ipv4>', '<ipv6>'],
                          'required' : True,
                          'example' : ['local 192.2.0.42']},
                   'endpoint' :
                        { 'help' : 'IP of remote tunnel endpoint',
                          'validvals' : ['<ipv4>', '<ipv6>'],
                          'required' : True,
                          'example' : ['endpoint 192.2.0.23']},
                   'ttl' :
                        { 'help' : 'TTL for tunnel packets',
                          'validvals' : ['<number>'],
                          'required' : False,
                          'example' : ['ttl 64']},
                   'tunnel-physdev' :
                        { 'help' : 'Physical underlay device to use for tunnel packets',
                          'validvals' : ['<interface>'],
                          'required' : False,
                          'example' : ['tunnel-physdev eth1']},
                 }
               }


    def __init__ (self, *args, **kargs):
        moduleBase.__init__ (self, *args, **kargs)
        self.ipcmd = None


    def _is_my_interface (self, ifaceobj):
        if ifaceobj.addr_method == "tunnel" and ifaceobj.get_attr_value_first ('mode'):
            return True
        return False


    def _has_config_changed (self, attrs_present, attrs_configured):
        for attr in set (attrs_present.keys () + attrs_configured.keys ()):
            # 'mode' is not present in attrs_configured and checked explicitly
            if attr == "mode":
                continue

            if attrs_present.get (attr, None) != attrs_configured.get (attr, None):
                return True

        return False


    def _up (self, ifaceobj):
        attr_map = {
            # attr_name -> ip route param name
            'local' : 'local',
            'endpoint' : 'remote',
            'ttl' : 'ttl',
            'tunnel-physdev' : 'dev',
        }

        mode = ifaceobj.get_attr_value_first ('mode')
        attrs = {}
        attrs_mapped = {}

        # Only include attributes which have been set and map ifupdown2 names
        # to attribute names expected by iproute
        for attr, iproute_attr in attr_map.items ():
            attr_val = ifaceobj.get_attr_value_first (attr)
            if attr_val != None:
                attrs_mapped[iproute_attr] = attr_val
		attrs[attr] = attr_val

        # Create the tunnel if it doesn't exist yet...
        if not self.ipcmd.link_exists(ifaceobj.name):
            self.ipcmd.tunnel_create (ifaceobj.name, mode, attrs_mapped)
            return

        # If it's present, check if there were changes
        current_attrs = self.ipcmd.link_get_linkinfo_attrs (ifaceobj.name)

        try:
            if current_attrs and current_attrs['mode'] != mode or self._has_config_changed (current_attrs, attrs):
                # Mode and some other changes are not possible without recreating the interface,
                # so just recreate it IFF there have been changes.
                self.ipcmd.link_delete (ifaceobj.name)
                self.ipcmd.tunnel_create (ifaceobj.name, mode, attrs_mapped)
        except Exception, e:
            self.log_warn (str (e))


    def _down (self, ifaceobj):
        if not ifupdownflags.flags.PERFMODE and not self.ipcmd.link_exists (ifaceobj.name):
           return
        try:
            self.ipcmd.link_delete (ifaceobj.name)
        except Exception, e:
            self.log_warn (str (e))


    def get_dependent_ifacenames (self, ifaceobj, ifacenames_all=None):
        if not self._is_my_interface (ifaceobj):
            return None

        device = ifaceobj.get_attr_value_first ('tunnel-physdev')
        if device:
            return [device]

        return None


    def _query_check_n_update (self, ifaceobj, ifaceobjcurr, attrname, attrval,
                               running_attrval):
        if not ifaceobj.get_attr_value_first (attrname):
            return

        if running_attrval and attrval == running_attrval:
           ifaceobjcurr.update_config_with_status (attrname, attrval, 0)
        else:
           ifaceobjcurr.update_config_with_status (attrname, running_attrval, 1)


    def _query_check (self, ifaceobj, ifaceobjcurr):
        if not self.ipcmd.link_exists (ifaceobj.name):
            return

        tunattrs = self.ipcmd.link_get_linkinfo_attrs (ifaceobj.name)
        if not tunattrs:
            ifaceobjcurr.check_n_update_config_with_status_many (ifaceobj, self.get_mod_attrs (), -1)
            return

        for attr in self.get_mod_attrs ():
            if not ifaceobj.get_attr_value_first (attr):
                continue

            # Validate all interface attributes set in the config.
            # Remote any leading 'tunnel-' prefix in front of the attr name
            # when accessing tunattrs parsed from 'ip -d link'.
            self._query_check_n_update (ifaceobj, ifaceobjcurr, attr,
                                        ifaceobj.get_attr_value_first (attr),
                                        tunattrs.get (attr.replace ("tunnel-", "")))


    # Operations supported by this addon (yet).
    _run_ops = {
        'pre-up' : _up,
        'post-down' : _down,
        'query-checkcurr' : _query_check
    }


    def get_ops (self):
        return self._run_ops.keys()


    def _init_command_handlers (self):
        if not self.ipcmd:
            self.ipcmd = iproute2 ()


    def run (self, ifaceobj, operation, query_ifaceobj = None, **extra_args):
        op_handler = self._run_ops.get (operation)
        if not op_handler:
            return

        if operation != 'query-running' and not self._is_my_interface (ifaceobj):
            return

        self._init_command_handlers ()
        if operation == 'query-checkcurr':
            op_handler (self, ifaceobj, query_ifaceobj)
        else:
            op_handler (self, ifaceobj)
