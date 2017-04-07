#    Copyright 2014 Rackspace
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy

import mock
from oslo_utils import uuidutils
import testtools

from octavia.common import constants
import octavia.common.context
from octavia.network import base as network_base
from octavia.network import data_models as network_models
from octavia.tests.functional.api.v2 import base


class TestLoadBalancer(base.BaseAPITest):
    root_tag = 'loadbalancer'
    root_tag_list = 'loadbalancers'

    def _assert_request_matches_response(self, req, resp, **optionals):
        self.assertTrue(uuidutils.is_uuid_like(resp.get('id')))
        req_name = req.get('name')
        req_description = req.get('description')
        if not req_name:
            self.assertEqual('', resp.get('name'))
        else:
            self.assertEqual(req.get('name'), resp.get('name'))
        if not req_description:
            self.assertEqual('', resp.get('description'))
        else:
            self.assertEqual(req.get('description'), resp.get('description'))
        self.assertEqual(constants.PENDING_CREATE,
                         resp.get('provisioning_status'))
        self.assertEqual(constants.OFFLINE, resp.get('operating_status'))
        self.assertEqual(req.get('admin_state_up', True),
                         resp.get('admin_state_up'))
        self.assertIsNotNone(resp.get('created_at'))
        self.assertIsNone(resp.get('updated_at'))
        for key, value in optionals.items():
            self.assertEqual(value, req.get(key))
        self.assert_final_lb_statuses(resp.get('id'))

    def test_empty_list(self):
        response = self.get(self.LBS_PATH)
        api_list = response.json.get(self.root_tag_list)
        self.assertEqual([], api_list)

    def test_create(self, **optionals):
        lb_json = {'name': 'test1',
                   'vip_subnet_id': uuidutils.generate_uuid(),
                   'project_id': self.project_id
                   }
        lb_json.update(optionals)
        body = self._build_body(lb_json)
        response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_request_matches_response(lb_json, api_lb)

    def test_create_without_vip(self):
        lb_json = {'name': 'test1',
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        response = self.post(self.LBS_PATH, body, status=400)
        err_msg = ('Validation failure: VIP must contain one of: '
                   'port_id, network_id, subnet_id.')
        self.assertEqual(err_msg, response.json.get('faultstring'))

    def test_create_with_empty_vip(self):
        lb_json = {'vip_subnet_id': '',
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        response = self.post(self.LBS_PATH, body, status=400)
        err_msg = ("Invalid input for field/attribute vip_subnet_id. "
                   "Value: ''. Value should be UUID format")
        self.assertEqual(err_msg, response.json.get('faultstring'))

    def test_create_with_invalid_vip_subnet(self):
        subnet_id = uuidutils.generate_uuid()
        lb_json = {'vip_subnet_id': subnet_id,
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_subnet") as mock_get_subnet:
            mock_get_subnet.side_effect = network_base.SubnetNotFound
            response = self.post(self.LBS_PATH, body, status=400)
            err_msg = 'Subnet {} not found.'.format(subnet_id)
            self.assertEqual(err_msg, response.json.get('faultstring'))

    def test_create_with_invalid_vip_network_subnet(self):
        network = network_models.Network(id=uuidutils.generate_uuid(),
                                         subnets=[])
        subnet_id = uuidutils.generate_uuid()
        lb_json = {
            'vip_subnet_id': subnet_id,
            'vip_network_id': network.id,
            'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network:
            mock_get_network.return_value = network
            response = self.post(self.LBS_PATH, body, status=400)
            err_msg = 'Subnet {} not found.'.format(subnet_id)
            self.assertEqual(err_msg, response.json.get('faultstring'))

    def test_create_with_vip_subnet_fills_network(self):
        subnet = network_models.Subnet(id=uuidutils.generate_uuid(),
                                       network_id=uuidutils.generate_uuid())
        lb_json = {'vip_subnet_id': subnet.id,
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_subnet") as mock_get_subnet:
            mock_get_subnet.return_value = subnet
            response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_request_matches_response(lb_json, api_lb)
        self.assertEqual(subnet.id, api_lb.get('vip_subnet_id'))
        self.assertEqual(subnet.network_id, api_lb.get('vip_network_id'))

    def test_create_with_vip_network_has_no_subnet(self):
        network = network_models.Network(id=uuidutils.generate_uuid(),
                                         subnets=[])
        lb_json = {
            'vip_network_id': network.id,
            'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network:
            mock_get_network.return_value = network
            response = self.post(self.LBS_PATH, body, status=400)
            err_msg = ("Validation failure: "
                       "Supplied network does not contain a subnet.")
            self.assertEqual(err_msg, response.json.get('faultstring'))

    def test_create_with_vip_network_picks_subnet_ipv4(self):
        network_id = uuidutils.generate_uuid()
        subnet1 = network_models.Subnet(id=uuidutils.generate_uuid(),
                                        network_id=network_id,
                                        ip_version=6)
        subnet2 = network_models.Subnet(id=uuidutils.generate_uuid(),
                                        network_id=network_id,
                                        ip_version=4)
        network = network_models.Network(id=network_id,
                                         subnets=[subnet1.id, subnet2.id])
        lb_json = {'vip_network_id': network.id,
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network, \
                mock.patch("octavia.network.drivers.noop_driver.driver"
                           ".NoopManager.get_subnet") as mock_get_subnet:
            mock_get_network.return_value = network
            mock_get_subnet.side_effect = [subnet1, subnet2]
            response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_request_matches_response(lb_json, api_lb)
        self.assertEqual(subnet2.id, api_lb.get('vip_subnet_id'))
        self.assertEqual(network_id, api_lb.get('vip_network_id'))

    def test_create_with_vip_network_picks_subnet_ipv6(self):
        network_id = uuidutils.generate_uuid()
        subnet = network_models.Subnet(id=uuidutils.generate_uuid(),
                                       network_id=network_id,
                                       ip_version=6)
        network = network_models.Network(id=network_id,
                                         subnets=[subnet.id])
        lb_json = {'vip_network_id': network_id,
                   'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network, \
                mock.patch("octavia.network.drivers.noop_driver.driver"
                           ".NoopManager.get_subnet") as mock_get_subnet:
            mock_get_network.return_value = network
            mock_get_subnet.return_value = subnet
            response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_request_matches_response(lb_json, api_lb)
        self.assertEqual(subnet.id, api_lb.get('vip_subnet_id'))
        self.assertEqual(network_id, api_lb.get('vip_network_id'))

    def test_create_with_vip_full(self):
        subnet = network_models.Subnet(id=uuidutils.generate_uuid())
        network = network_models.Network(id=uuidutils.generate_uuid(),
                                         subnets=[subnet])
        port = network_models.Port(id=uuidutils.generate_uuid(),
                                   network_id=network.id)
        lb_json = {
            'name': 'test1', 'description': 'test1_desc',
            'vip_address': '10.0.0.1', 'vip_subnet_id': subnet.id,
            'vip_network_id': network.id, 'vip_port_id': port.id,
            'admin_state_up': False, 'project_id': self.project_id}
        body = self._build_body(lb_json)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network, \
                mock.patch("octavia.network.drivers.noop_driver.driver"
                           ".NoopManager.get_port") as mock_get_port:
            mock_get_network.return_value = network
            mock_get_port.return_value = port
            response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_request_matches_response(lb_json, api_lb)
        self.assertEqual('10.0.0.1', api_lb.get('vip_address'))
        self.assertEqual(subnet.id, api_lb.get('vip_subnet_id'))
        self.assertEqual(network.id, api_lb.get('vip_network_id'))
        self.assertEqual(port.id, api_lb.get('vip_port_id'))

    def test_create_with_long_name(self):
        lb_json = {'name': 'n' * 256,
                   'vip_subnet_id': uuidutils.generate_uuid()}
        self.post(self.LBS_PATH, lb_json, status=400)

    def test_create_with_long_description(self):
        lb_json = {'description': 'n' * 256,
                   'vip_subnet_id': uuidutils.generate_uuid()}
        self.post(self.LBS_PATH, lb_json, status=400)

    def test_create_with_nonuuid_vip_attributes(self):
        lb_json = {'vip_subnet_id': 'HI'}
        self.post(self.LBS_PATH, lb_json, status=400)

    def test_create_with_project_id(self):
        self.test_create(project_id=uuidutils.generate_uuid())

    def test_get_all_admin(self):
        project_id = uuidutils.generate_uuid()
        lb1 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb1', project_id=self.project_id)
        lb2 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb2', project_id=project_id)
        lb3 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb3', project_id=project_id)
        response = self.get(self.LBS_PATH)
        lbs = response.json.get(self.root_tag_list)
        self.assertEqual(3, len(lbs))
        lb_id_names = [(lb.get('id'), lb.get('name')) for lb in lbs]
        lb1 = lb1.get(self.root_tag)
        lb2 = lb2.get(self.root_tag)
        lb3 = lb3.get(self.root_tag)
        self.assertIn((lb1.get('id'), lb1.get('name')), lb_id_names)
        self.assertIn((lb2.get('id'), lb2.get('name')), lb_id_names)
        self.assertIn((lb3.get('id'), lb3.get('name')), lb_id_names)

    def test_get_all_non_admin(self):
        project_id = uuidutils.generate_uuid()
        self.create_load_balancer(uuidutils.generate_uuid(),
                                  name='lb1', project_id=project_id)
        self.create_load_balancer(uuidutils.generate_uuid(),
                                  name='lb2', project_id=project_id)
        lb3 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb3', project_id=self.project_id)
        lb3 = lb3.get(self.root_tag)

        auth_strategy = self.conf.conf.get('auth_strategy')
        self.conf.config(auth_strategy=constants.KEYSTONE)
        with mock.patch.object(octavia.common.context.Context, 'project_id',
                               self.project_id):
            response = self.get(self.LBS_PATH)
        self.conf.config(auth_strategy=auth_strategy)

        lbs = response.json.get(self.root_tag_list)
        self.assertEqual(1, len(lbs))
        lb_id_names = [(lb.get('id'), lb.get('name')) for lb in lbs]
        self.assertIn((lb3.get('id'), lb3.get('name')), lb_id_names)

    def test_get_all_by_project_id(self):
        project1_id = uuidutils.generate_uuid()
        project2_id = uuidutils.generate_uuid()
        lb1 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb1',
                                        project_id=project1_id)
        lb2 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb2',
                                        project_id=project1_id)
        lb3 = self.create_load_balancer(uuidutils.generate_uuid(),
                                        name='lb3',
                                        project_id=project2_id)
        response = self.get(self.LBS_PATH,
                            params={'project_id': project1_id})
        lbs = response.json.get(self.root_tag_list)

        self.assertEqual(2, len(lbs))

        lb_id_names = [(lb.get('id'), lb.get('name')) for lb in lbs]
        lb1 = lb1.get(self.root_tag)
        lb2 = lb2.get(self.root_tag)
        lb3 = lb3.get(self.root_tag)
        self.assertIn((lb1.get('id'), lb1.get('name')), lb_id_names)
        self.assertIn((lb2.get('id'), lb2.get('name')), lb_id_names)
        response = self.get(self.LBS_PATH,
                            params={'project_id': project2_id})
        lbs = response.json.get(self.root_tag_list)
        lb_id_names = [(lb.get('id'), lb.get('name')) for lb in lbs]
        self.assertEqual(1, len(lbs))
        self.assertIn((lb3.get('id'), lb3.get('name')), lb_id_names)

    def test_get(self):
        project_id = uuidutils.generate_uuid()
        subnet = network_models.Subnet(id=uuidutils.generate_uuid())
        network = network_models.Network(id=uuidutils.generate_uuid(),
                                         subnets=[subnet])
        port = network_models.Port(id=uuidutils.generate_uuid(),
                                   network_id=network.id)
        with mock.patch("octavia.network.drivers.noop_driver.driver"
                        ".NoopManager.get_network") as mock_get_network, \
                mock.patch("octavia.network.drivers.noop_driver.driver"
                           ".NoopManager.get_port") as mock_get_port:
            mock_get_network.return_value = network
            mock_get_port.return_value = port

            lb = self.create_load_balancer(subnet.id,
                                           vip_address='10.0.0.1',
                                           vip_network_id=network.id,
                                           vip_port_id=port.id,
                                           name='lb1',
                                           project_id=project_id,
                                           description='desc1',
                                           admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        response = self.get(
            self.LB_PATH.format(
                lb_id=lb_dict.get('id'))).json.get(self.root_tag)
        self.assertEqual('lb1', response.get('name'))
        self.assertEqual(project_id, response.get('project_id'))
        self.assertEqual('desc1', response.get('description'))
        self.assertFalse(response.get('admin_state_up'))
        self.assertEqual('10.0.0.1', response.get('vip_address'))
        self.assertEqual(subnet.id, response.get('vip_subnet_id'))
        self.assertEqual(network.id, response.get('vip_network_id'))
        self.assertEqual(port.id, response.get('vip_port_id'))

    def test_get_bad_lb_id(self):
        path = self.LB_PATH.format(lb_id='SEAN-CONNERY')
        self.get(path, status=404)

    def test_update(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb_json = self._build_body({'name': 'lb2'})
        lb = self.set_lb_status(lb_dict.get('id'))
        response = self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')),
                            lb_json)
        api_lb = response.json.get(self.root_tag)
        self.assertIsNotNone(api_lb.get('vip_subnet_id'))
        self.assertEqual('lb1', api_lb.get('name'))
        self.assertEqual(project_id, api_lb.get('project_id'))
        self.assertEqual('desc1', api_lb.get('description'))
        self.assertFalse(api_lb.get('admin_state_up'))
        self.assertEqual(lb.get('operational_status'),
                         api_lb.get('operational_status'))
        self.assertIsNotNone(api_lb.get('created_at'))
        self.assertIsNotNone(api_lb.get('updated_at'))
        self.assert_final_lb_statuses(api_lb.get('id'))

    def test_update_with_vip(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb_json = self._build_body({'vip_subnet_id': '1234'})
        lb = self.set_lb_status(lb_dict.get('id'))
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')),
                 lb_json, status=400)

    def test_update_bad_lb_id(self):
        path = self.LB_PATH.format(lb_id='SEAN-CONNERY')
        self.put(path, body={}, status=404)

    def test_update_pending_create(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb_json = self._build_body({'name': 'Roberto'})
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')),
                 lb_json, status=409)

    def test_delete_pending_create(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')), status=409)

    def test_update_pending_update(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb_json = self._build_body({'name': 'Bob'})
        lb = self.set_lb_status(lb_dict.get('id'))
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')), lb_json)
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')),
                 lb_json, status=409)

    def test_delete_pending_update(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_json = self._build_body({'name': 'Steve'})
        lb_dict = lb.get(self.root_tag)
        lb = self.set_lb_status(lb_dict.get('id'))
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')), lb_json)
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')), status=409)

    def test_delete_with_error_status(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb = self.set_lb_status(lb_dict.get('id'), status=constants.ERROR)
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')), status=204)

    def test_update_pending_delete(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb = self.set_lb_status(lb_dict.get('id'))
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')))
        lb_json = self._build_body({'name': 'John'})
        self.put(self.LB_PATH.format(lb_id=lb_dict.get('id')),
                 lb_json, status=409)

    def test_delete_pending_delete(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb = self.set_lb_status(lb_dict.get('id'))
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')))
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')), status=409)

    def test_delete(self):
        project_id = uuidutils.generate_uuid()
        lb = self.create_load_balancer(uuidutils.generate_uuid(),
                                       name='lb1',
                                       project_id=project_id,
                                       description='desc1',
                                       admin_state_up=False)
        lb_dict = lb.get(self.root_tag)
        lb = self.set_lb_status(lb_dict.get('id'))
        self.delete(self.LB_PATH.format(lb_id=lb_dict.get('id')))
        response = self.get(self.LB_PATH.format(lb_id=lb_dict.get('id')))
        api_lb = response.json.get(self.root_tag)
        self.assertEqual('lb1', api_lb.get('name'))
        self.assertEqual('desc1', api_lb.get('description'))
        self.assertEqual(project_id, api_lb.get('project_id'))
        self.assertFalse(api_lb.get('admin_state_up'))
        self.assertEqual(lb.get('operational_status'),
                         api_lb.get('operational_status'))
        self.assert_final_lb_statuses(api_lb.get('id'), delete=True)

    def test_delete_bad_lb_id(self):
        path = self.LB_PATH.format(lb_id='bad_uuid')
        self.delete(path, status=404)


class TestLoadBalancerGraph(base.BaseAPITest):

    root_tag = 'loadbalancer'

    def setUp(self):
        super(TestLoadBalancerGraph, self).setUp()
        self._project_id = uuidutils.generate_uuid()

    def _build_body(self, json):
        return {self.root_tag: json}

    def _assert_graphs_equal(self, expected_graph, observed_graph):
        observed_graph_copy = copy.deepcopy(observed_graph)
        del observed_graph_copy['created_at']
        del observed_graph_copy['updated_at']
        obs_lb_id = observed_graph_copy.pop('id')

        self.assertTrue(uuidutils.is_uuid_like(obs_lb_id))
        expected_listeners = expected_graph.pop('listeners', [])
        observed_listeners = observed_graph_copy.pop('listeners', [])
        self.assertEqual(expected_graph, observed_graph_copy)
        for observed_listener in observed_listeners:
            del observed_listener['created_at']
            del observed_listener['updated_at']

            self.assertTrue(uuidutils.is_uuid_like(
                observed_listener.pop('id')))
            default_pool = observed_listener.get('default_pool')
            if default_pool:
                observed_listener.pop('default_pool_id')
                self.assertTrue(default_pool.get('id'))
                default_pool.pop('id')
                default_pool.pop('created_at')
                default_pool.pop('updated_at')
                hm = default_pool.get('healthmonitor')
                if hm:
                    self.assertTrue(hm.get('id'))
                    hm.pop('id')
                for member in default_pool.get('members', []):
                    self.assertTrue(member.get('id'))
                    member.pop('id')
                    member.pop('created_at')
                    member.pop('updated_at')
            if observed_listener.get('sni_containers'):
                observed_listener['sni_containers'].sort()
            o_l7policies = observed_listener.get('l7policies')
            if o_l7policies:
                for o_l7policy in o_l7policies:
                    if o_l7policy.get('redirect_pool'):
                        r_pool = o_l7policy.get('redirect_pool')
                        self.assertTrue(r_pool.get('id'))
                        r_pool.pop('id')
                        r_pool.pop('created_at')
                        r_pool.pop('updated_at')
                        self.assertTrue(o_l7policy.get('redirect_pool_id'))
                        o_l7policy.pop('redirect_pool_id')
                        if r_pool.get('members'):
                            for r_member in r_pool.get('members'):
                                self.assertTrue(r_member.get('id'))
                                r_member.pop('id')
                                r_member.pop('created_at')
                                r_member.pop('updated_at')
                    self.assertTrue(o_l7policy.get('id'))
                    o_l7policy.pop('id')
                    l7rules = o_l7policy.get('l7rules')
                    for l7rule in l7rules:
                        self.assertTrue(l7rule.get('id'))
                        l7rule.pop('id')
            self.assertIn(observed_listener, expected_listeners)

    def _get_lb_bodies(self, create_listeners, expected_listeners):
        create_lb = {
            'name': 'lb1',
            'project_id': self._project_id,
            'vip_subnet_id': None,
            'listeners': create_listeners
        }
        expected_lb = {
            'description': None,
            'enabled': True,
            'provisioning_status': constants.PENDING_CREATE,
            'operating_status': constants.OFFLINE,
            'vip_subnet_id': None,
            'vip_address': None,
        }
        expected_lb.update(create_lb)
        expected_lb['listeners'] = expected_listeners
        return create_lb, expected_lb

    def _get_listener_bodies(self, name='listener1', protocol_port=80,
                             create_default_pool=None,
                             expected_default_pool=None,
                             create_l7policies=None,
                             expected_l7policies=None,
                             create_sni_containers=None,
                             expected_sni_containers=None):
        create_listener = {
            'name': name,
            'protocol_port': protocol_port,
            'protocol': constants.PROTOCOL_HTTP,
            'project_id': self._project_id
        }
        expected_listener = {
            'description': None,
            'tls_certificate_id': None,
            'sni_containers': [],
            'connection_limit': None,
            'enabled': True,
            'provisioning_status': constants.PENDING_CREATE,
            'operating_status': constants.OFFLINE,
            'insert_headers': {}
        }
        if create_sni_containers:
            create_listener['sni_containers'] = create_sni_containers
        expected_listener.update(create_listener)
        if create_default_pool:
            pool = create_default_pool
            create_listener['default_pool'] = pool
            if pool.get('id'):
                create_listener['default_pool_id'] = pool['id']
        if create_l7policies:
            l7policies = create_l7policies
            create_listener['l7policies'] = l7policies
        if expected_default_pool:
            expected_listener['default_pool'] = expected_default_pool
        if expected_sni_containers:
            expected_listener['sni_containers'] = expected_sni_containers
        if expected_l7policies:
            expected_listener['l7policies'] = expected_l7policies
        return create_listener, expected_listener

    def _get_pool_bodies(self, name='pool1', create_members=None,
                         expected_members=None, create_hm=None,
                         expected_hm=None, protocol=constants.PROTOCOL_HTTP,
                         session_persistence=True):
        create_pool = {
            'name': name,
            'protocol': protocol,
            'lb_algorithm': constants.LB_ALGORITHM_ROUND_ROBIN,
            'project_id': self._project_id
        }
        if session_persistence:
            create_pool['session_persistence'] = {
                'type': constants.SESSION_PERSISTENCE_SOURCE_IP,
                'cookie_name': None}
        if create_members:
            create_pool['members'] = create_members
        if create_hm:
            create_pool['health_monitor'] = create_hm
        expected_pool = {
            'description': None,
            'session_persistence': None,
            'members': [],
            'enabled': True,
            'operating_status': constants.OFFLINE
        }
        expected_pool.update(create_pool)
        if expected_members:
            expected_pool['members'] = expected_members
        if expected_hm:
            expected_pool['health_monitor'] = expected_hm
        return create_pool, expected_pool

    def _get_member_bodies(self, protocol_port=80):
        create_member = {
            'ip_address': '10.0.0.1',
            'protocol_port': protocol_port,
            'project_id': self._project_id
        }
        expected_member = {
            'weight': 1,
            'enabled': True,
            'subnet_id': None,
            'operating_status': constants.OFFLINE
        }
        expected_member.update(create_member)
        return create_member, expected_member

    def _get_hm_bodies(self):
        create_hm = {
            'type': constants.HEALTH_MONITOR_PING,
            'delay': 1,
            'timeout': 1,
            'fall_threshold': 1,
            'rise_threshold': 1,
            'project_id': self._project_id
        }
        expected_hm = {
            'http_method': 'GET',
            'url_path': '/',
            'expected_codes': '200',
            'enabled': True
        }
        expected_hm.update(create_hm)
        return create_hm, expected_hm

    def _get_sni_container_bodies(self):
        create_sni_container1 = uuidutils.generate_uuid()
        create_sni_container2 = uuidutils.generate_uuid()
        create_sni_containers = [create_sni_container1, create_sni_container2]
        expected_sni_containers = [create_sni_container1,
                                   create_sni_container2]
        expected_sni_containers.sort()
        return create_sni_containers, expected_sni_containers

    def _get_l7policies_bodies(self, create_pool=None, expected_pool=None,
                               create_l7rules=None, expected_l7rules=None):
        create_l7policies = []
        if create_pool:
            create_l7policy = {
                'action': constants.L7POLICY_ACTION_REDIRECT_TO_POOL,
                'redirect_pool': create_pool,
                'position': 1,
                'enabled': False
            }
        else:
            create_l7policy = {
                'action': constants.L7POLICY_ACTION_REDIRECT_TO_URL,
                'redirect_url': 'http://127.0.0.1/',
                'position': 1,
                'enabled': False
            }
        create_l7policies.append(create_l7policy)
        expected_l7policy = {
            'name': None,
            'description': None,
            'redirect_url': None,
            'l7rules': []
        }
        expected_l7policy.update(create_l7policy)
        expected_l7policies = []
        if expected_pool:
            if create_pool.get('id'):
                expected_l7policy['redirect_pool_id'] = create_pool.get('id')
            expected_l7policy['redirect_pool'] = expected_pool
        expected_l7policies.append(expected_l7policy)
        if expected_l7rules:
            expected_l7policies[0]['l7rules'] = expected_l7rules
        if create_l7rules:
            create_l7policies[0]['l7rules'] = create_l7rules
        return create_l7policies, expected_l7policies

    def _get_l7rules_bodies(self, value="localhost"):
        create_l7rules = [{
            'type': constants.L7RULE_TYPE_HOST_NAME,
            'compare_type': constants.L7RULE_COMPARE_TYPE_EQUAL_TO,
            'value': value,
            'invert': False
        }]
        expected_l7rules = [{
            'key': None
        }]
        expected_l7rules[0].update(create_l7rules[0])
        return create_l7rules, expected_l7rules

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_listener(self):
        create_listener, expected_listener = self._get_listener_bodies()
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        body = self._build_body(create_lb)
        response = self.post(self.LBS_PATH, body)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_many_listeners(self):
        create_listener1, expected_listener1 = self._get_listener_bodies()
        create_listener2, expected_listener2 = self._get_listener_bodies(
            name='listener2', protocol_port=81
        )
        create_lb, expected_lb = self._get_lb_bodies(
            [create_listener1, create_listener2],
            [expected_listener1, expected_listener2])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_listener_one_pool(self):
        create_pool, expected_pool = self._get_pool_bodies()
        create_listener, expected_listener = self._get_listener_bodies(
            create_default_pool=create_pool,
            expected_default_pool=expected_pool
        )
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_many_listeners_one_pool(self):
        create_pool1, expected_pool1 = self._get_pool_bodies()
        create_pool2, expected_pool2 = self._get_pool_bodies(name='pool2')
        create_listener1, expected_listener1 = self._get_listener_bodies(
            create_default_pool=create_pool1,
            expected_default_pool=expected_pool1
        )
        create_listener2, expected_listener2 = self._get_listener_bodies(
            create_default_pool=create_pool2,
            expected_default_pool=expected_pool2,
            name='listener2', protocol_port=81
        )
        create_lb, expected_lb = self._get_lb_bodies(
            [create_listener1, create_listener2],
            [expected_listener1, expected_listener2])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_listener_one_member(self):
        create_member, expected_member = self._get_member_bodies()
        create_pool, expected_pool = self._get_pool_bodies(
            create_members=[create_member],
            expected_members=[expected_member])
        create_listener, expected_listener = self._get_listener_bodies(
            create_default_pool=create_pool,
            expected_default_pool=expected_pool)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_listener_one_hm(self):
        create_hm, expected_hm = self._get_hm_bodies()
        create_pool, expected_pool = self._get_pool_bodies(
            create_hm=create_hm,
            expected_hm=expected_hm)
        create_listener, expected_listener = self._get_listener_bodies(
            create_default_pool=create_pool,
            expected_default_pool=expected_pool)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_listener_sni_containers(self):
        create_sni_containers, expected_sni_containers = (
            self._get_sni_container_bodies())
        create_listener, expected_listener = self._get_listener_bodies(
            create_sni_containers=create_sni_containers,
            expected_sni_containers=expected_sni_containers)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_l7policy_redirect_pool_no_rule(self):
        create_pool, expected_pool = self._get_pool_bodies(create_members=[],
                                                           expected_members=[])
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=create_pool, expected_pool=expected_pool)
        create_listener, expected_listener = self._get_listener_bodies(
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_l7policy_redirect_pool_one_rule(self):
        create_pool, expected_pool = self._get_pool_bodies(create_members=[],
                                                           expected_members=[])
        create_l7rules, expected_l7rules = self._get_l7rules_bodies()
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=create_pool, expected_pool=expected_pool,
            create_l7rules=create_l7rules, expected_l7rules=expected_l7rules)
        create_listener, expected_listener = self._get_listener_bodies(
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_l7policy_redirect_pool_bad_rule(self):
        create_pool, expected_pool = self._get_pool_bodies(create_members=[],
                                                           expected_members=[])
        create_l7rules, expected_l7rules = self._get_l7rules_bodies(
            value="local host")
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=create_pool, expected_pool=expected_pool,
            create_l7rules=create_l7rules, expected_l7rules=expected_l7rules)
        create_listener, expected_listener = self._get_listener_bodies(
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        self.post(self.LBS_PATH, create_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_l7policies_one_redirect_pool_one_rule(self):
        create_pool, expected_pool = self._get_pool_bodies(create_members=[],
                                                           expected_members=[])
        create_l7rules, expected_l7rules = self._get_l7rules_bodies()
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=create_pool, expected_pool=expected_pool,
            create_l7rules=create_l7rules, expected_l7rules=expected_l7rules)
        c_l7policies_url, e_l7policies_url = self._get_l7policies_bodies()
        for policy in c_l7policies_url:
            policy['position'] = 2
            create_l7policies.append(policy)
        for policy in e_l7policies_url:
            policy['position'] = 2
            expected_l7policies.append(policy)
        create_listener, expected_listener = self._get_listener_bodies(
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_l7policies_redirect_pools_no_rules(self):
        create_pool, expected_pool = self._get_pool_bodies()
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=create_pool, expected_pool=expected_pool)
        r_create_pool, r_expected_pool = self._get_pool_bodies()
        c_l7policies_url, e_l7policies_url = self._get_l7policies_bodies(
            create_pool=r_create_pool, expected_pool=r_expected_pool)
        for policy in c_l7policies_url:
            policy['position'] = 2
            create_l7policies.append(policy)
        for policy in e_l7policies_url:
            policy['position'] = 2
            expected_l7policies.append(policy)
        create_listener, expected_listener = self._get_listener_bodies(
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_with_one_of_everything(self):
        create_member, expected_member = self._get_member_bodies()
        create_hm, expected_hm = self._get_hm_bodies()
        create_pool, expected_pool = self._get_pool_bodies(
            create_members=[create_member],
            expected_members=[expected_member],
            create_hm=create_hm,
            expected_hm=expected_hm,
            protocol=constants.PROTOCOL_TCP)
        create_sni_containers, expected_sni_containers = (
            self._get_sni_container_bodies())
        create_l7rules, expected_l7rules = self._get_l7rules_bodies()
        r_create_member, r_expected_member = self._get_member_bodies(
            protocol_port=88)
        r_create_pool, r_expected_pool = self._get_pool_bodies(
            create_members=[r_create_member],
            expected_members=[r_expected_member])
        create_l7policies, expected_l7policies = self._get_l7policies_bodies(
            create_pool=r_create_pool, expected_pool=r_expected_pool,
            create_l7rules=create_l7rules, expected_l7rules=expected_l7rules)
        create_listener, expected_listener = self._get_listener_bodies(
            create_default_pool=create_pool,
            expected_default_pool=expected_pool,
            create_l7policies=create_l7policies,
            expected_l7policies=expected_l7policies,
            create_sni_containers=create_sni_containers,
            expected_sni_containers=expected_sni_containers)
        create_lb, expected_lb = self._get_lb_bodies([create_listener],
                                                     [expected_listener])
        response = self.post(self.LBS_PATH, create_lb)
        api_lb = response.json.get(self.root_tag)
        self._assert_graphs_equal(expected_lb, api_lb)

    @testtools.skip('Skip until complete v2 merge')
    def test_db_create_failure(self):
        create_listener, expected_listener = self._get_listener_bodies()
        create_lb, _ = self._get_lb_bodies([create_listener],
                                           [expected_listener])
        with mock.patch('octavia.db.repositories.Repositories.'
                        'create_load_balancer_tree') as repo_mock:
            repo_mock.side_effect = Exception('I am a DB Error')
            self.post(self.LBS_PATH, create_lb, status=500)