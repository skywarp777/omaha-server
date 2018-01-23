# coding: utf8

"""
This software is licensed under the Apache 2 license, quoted below.

Copyright 2014 Crystalnix Limited

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.
"""
import os
import logging
import requests

from django.views.generic import View
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.http import HttpResponseBadRequest

from django_select2.views import AutoResponseView
from lxml.etree import XMLSyntaxError
from raven import Client

from omaha.builder import build_response
from omaha_server.utils import get_client_ip
from omaha.models import Request, Version
from builder import get_version


logger = logging.getLogger(__name__)
client = Client(getattr(settings, 'RAVEN_DSN_STACKTRACE', None), name=getattr(settings, 'HOST_NAME', None),
                release=getattr(settings, 'APP_VERSION', None))


class UpdateView(View):
    http_method_names = ['post']

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(UpdateView, self).dispatch(*args, **kwargs)

    def post(self, request):
        try:
            response = build_response(request.body, ip=get_client_ip(request))
        except XMLSyntaxError:
            logger.error('UpdateView', exc_info=True, extra=dict(request=request))
            msg = b"""<?xml version="1.0" encoding="utf-8"?>
<data>
    <message>
        Bad Request
    </message>
</data>"""
            return HttpResponse(msg, status=400, content_type="text/html; charset=utf-8")
        return HttpResponse(response, content_type="text/xml; charset=utf-8")


class FilterByUserIDResponseView(AutoResponseView):
    max_results = 10

    def get(self, request, *args, **kwargs):
        term = request.GET.get('term', '')
        app = request.GET.get('app_id', '')

        if not term.startswith('{'):
            term = '{' + term
        term = term.upper()

        requests = Request.objects.filter(apprequest__appid=app, userid__startswith=term)
        requests = requests.distinct('userid').values_list('userid', flat=True)[:self.max_results]
        return JsonResponse({
            'results': [
                {
                    'text': userid,
                    'id': userid,
                }
                for userid in requests
                ],
            'more': False
        })


class UsageStatsView(View):
    http_method_names = ['post', 'get']

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(UsageStatsView, self).dispatch(*args, **kwargs)

    def post(self, request):
        client.captureMessage('Omaha Clients Usage Statistics: {0}'.format(request.body), tags=request.GET,
                              data={'level': 20, 'logger': 'usagestats'})
        return HttpResponse('ok')


class CodeRedView(View):
    http_method_names = ['get']

    @csrf_exempt
    def dispatch(self, *args, **kwargs):
        return super(CodeRedView, self).dispatch(*args, **kwargs)

    def get(self, request, *args, **kwargs):
        try:
            version = get_version(
                app_id=request.GET.get('appid', ''),
                channel=os.environ.get('CODE_RED_CHANNEL', 'code_red'),
                userid=request.GET.get('userid', ''),
                platform='win',
                version='0.0.0.0'
            )
        except Version.DoesNotExist:
            return HttpResponseBadRequest(
                content='Error: Version does not exist'
            )

        req_to_s3 = requests.get(
            version.file_absolute_url,
            allow_redirects=True
        )
        filename = version.file_package_name
        response = HttpResponse(status=200)
        response.write(req_to_s3.content)
        response['Content-Type'] = 'application/x-exe'
        response['Content-Disposition'] = 'attachment; filename=' + filename
        return response
