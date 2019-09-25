"""
NOTE from Matt:

I don't know how or why, but this file goes through some sort of post-processing
before landing at
    centos@horus:/opt/anaconda2/envs/cabot/lib/python2.7/site-packages/cabot_alert_twilio/models.py

Since I rarely make tiny changes, I've just been hand-editing that file.

See /opt/cabot/log/celery.log for error messages if this code doesn't work.
You also need to actually fully restart Cabot web service to pick up changes,
since these changes are running in the background celery processes.
"""
from os import environ as env

from django.conf import settings
from django.core.urlresolvers import reverse
from django.template import Context, Template
from django import forms

from twilio.rest import TwilioRestClient
from twilio import twiml
import requests
import logging

from cabot.plugins.models import AlertPlugin, AlertPluginModel

telephone_template = "This is an urgent message from Arachnys monitoring. Service \"{{ service.name }}\" is erroring. Please check Cabot urgently."
sms_template = "{{ service.name }} {% if service.overall_status == service.PASSING_STATUS %}is back to normal{% else %}{{ service.overall_status }} due to: {{ service.kqr_failing_names }} {% endif %}"

logger = logging.getLogger(__name__)

# We will attach this to TwilioPhoneCallAlert but it will be accessed
# by both plugins
class TwilioUserSettingsForm(forms.Form):
    name = "Twilio Plugin"
    phone_number = forms.CharField(max_length=30)

    def clean(self, *args, **kwargs):
        phone_number = self.cleaned_data['phone_number']
        if not phone_number.startswith('+'):
            self.cleaned_data['phone_number'] = '+{}'.format(phone_number)
        return super(TwilioUserSettingsForm, self).clean()


class TwilioPhoneCallAlert(AlertPlugin):
    name = "Twilio Phone Call"
    slug = "cabot_alert_twilio"
    author = "Jonathan Balls"
    version = "0.0.1"
    font_icon = "fa fa-phone"

    plugin_variables = [
        'TWILIO_ACCOUNT_SID',
	'TWILIO_AUTH_TOKEN',
	'TWILIO_OUTGOING_NUMBER'
    ]

    user_config_form = TwilioUserSettingsForm

    def send_alert(self, service, users, duty_officers):

        account_sid = env.get('TWILIO_ACCOUNT_SID')
        auth_token  = env.get('TWILIO_AUTH_TOKEN')
        outgoing_number = env.get('TWILIO_OUTGOING_NUMBER')
        url = '%s://%s%s' % (settings.WWW_SCHEME, settings.WWW_HTTP_HOST,
            reverse('twiml-callback', kwargs={'service_id': service.id}))

        # No need to call to say things are resolved
        if service.overall_status != service.CRITICAL_STATUS:
            return
        client = TwilioRestClient(
            account_sid, auth_token)

	mobiles = [u.cabot_alert_twilio_settings.phone_number for u in users]

        for mobile in mobiles:
            try:
                client.calls.create(
                    to=mobile,
                    from_=outgoing_number,
                    url=url,
                    method='GET',
                )
            except Exception, e:
                logger.exception('Error making twilio phone call: %s' % e)


class TwilioSMSAlert(AlertPlugin):
    name = "Twilio SMS"
    slug = "cabot_alert_twilio_sms"
    author = "Jonathan Balls"
    version = "0.0.1"
    font_icon = "fa fa-phone"

    plugin_variables = [
        'TWILIO_ACCOUNT_SID',
        'TWILIO_AUTH_TOKEN',
        'TWILIO_OUTGOING_NUMBER'
    ]

    def send_alert(self, service, users, duty_officers):
        account_sid = env.get('TWILIO_ACCOUNT_SID')
        auth_token  = env.get('TWILIO_AUTH_TOKEN')
        outgoing_number = env.get('TWILIO_OUTGOING_NUMBER')

        all_users = list(users) + list(duty_officers)

        client = TwilioRestClient(
            account_sid, auth_token)
        mobiles = [u.cabot_alert_twilio_settings.phone_number for u in users]

        # Hack to maintain compatibilty with non-hacked Cabot
        if not hasattr(service, "kqr_failing_names"):
            service.kqr_failing_names = "unknown"

        c = Context({
            'service': service,
            'host': settings.WWW_HTTP_HOST,
            'scheme': settings.WWW_SCHEME,
        })
        message = Template(sms_template).render(c)
        for mobile in mobiles:
            try:
                client.sms.messages.create(
                    to=mobile,
                    from_=outgoing_number,
                    body=message[:159],  # Twilio has a 160 character limit for texts
                )
            except Exception, e:
                logger.exception('Error sending twilio sms: %s %s' % (e, message))

