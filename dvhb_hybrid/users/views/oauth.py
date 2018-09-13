import logging

import aioauth_client
from aiohttp.web_exceptions import HTTPNotFound, HTTPFound
from django.contrib.auth.hashers import make_password
from django.utils.crypto import get_random_string
from yarl import URL

from dvhb_hybrid.amodels import method_connect_once
from dvhb_hybrid.permissions import gen_api_key

logger = logging.getLogger(__name__)

# Prevent limiting data to fields defined in aioauth_client.User
aioauth_client.User = lambda **kwargs: kwargs


class UserOAuthView:

    @property
    def model(self):
        return self.request.app.m.user

    @property
    def conf(self):
        return getattr(self.request.app.config, 'social', {})

    async def _on_login_successful(self, user, connection):
        await gen_api_key(user.id, request=self.request)
        self.request.user = user
        await self.request.app.m.user_action_log_entry.create_login(self.request, connection=connection)
        logger.info("User '%s' logged in via oauth", user.email)
        # Redirect to our login success page
        self._redirect(self.conf.url.success, headers={'Authorization': self.request.api_key})

    def _get_client(self, provider):
        if not self.conf or provider not in self.conf:
            raise HTTPNotFound(reason="OAuth provider not configured")

        # Initialize OAuth2 client
        client_class = aioauth_client.ClientRegistry.clients[provider]
        client = client_class(**self.conf[provider])
        url = str(self.request.url.with_query(''))
        url = url.replace('/redirect', '/callback')
        client.params['redirect_uri'] = url
        return client

    @staticmethod
    def _redirect(url, headers=None):
        logger.info("Redirecting to URL '%s'...", url)
        raise HTTPFound(url, headers=headers)

    async def oauth_redirect(self, request, provider):
        client = self._get_client(provider)
        # Redirect to the oauth provider's auth page
        self._redirect(client.get_authorize_url())

    @method_connect_once
    async def oauth_callback(self, request, provider, access_token=None, connection=None):
        client = self._get_client(provider)
        provider_data = {}

        logger.debug("Provider '%s' callback query: %s", provider, request.query)

        if not access_token:
            if 'error' in request.query:
                # Redirect to our oauth reject page
                url = URL(self.conf.url.reject).with_query(request.query)
                self._redirect(url)
            else:
                assert client.shared_key in request.query
                # Request access token from provider
                _, provider_data = await client.get_access_token(request.query)
                logger.debug("Obtained provider_data '%s' for provider '%s'", provider_data, provider)

        # Obtain user profile data from provider
        user_info, raw_data = await client.user_info()

        logger.debug("Obtained user_info %s (%s) for provider '%s'", user_info, raw_data, provider)

        if not user_info.get('email') and provider_data.get('email'):
            user_info['email'] = provider_data.get('email')

        # Remove None values from user info if any
        user_info = {k: v for k, v in user_info.items() if v is not None}

        # Try to find user in DB by provider ID
        user = await self.model.get_by_oauth_provider(provider, user_info['id'],  connection=connection)
        if user is not None:
            # User need to be activated
            if not user.is_active:
                # Redirect to our activation page
                self._redirect(self.conf.url.need_activate)
            else:
                await self._on_login_successful(user, connection)

        # No email address obtained
        if not user_info.get('email'):
            # Redirect to our registration page
            url = URL(self.conf.url.reg).with_query(user_info)
            self._redirect(url)

        # Try to find user by email address
        user = await self.model.get_user_by_email(user_info['email'],  connection=connection)

        # User found
        if user is not None:
            if not user.is_active:
                # Redirect to our user activation page
                url = self.conf.url.need_activate
                self._redirect(url)
        else:
            # Create new user
            user = self.model(email=user_info['email'], password=make_password(get_random_string()), is_active=True)
            self.model.set_defaults(user)
            await user.save(connection=connection)
            await user.save_oauth_info(provider, user_info['id'], connection=connection)
            await user.patch_profile(user_info, connection=connection)
            logger.info(
                "Created new user email '%s' for oauth provider '%s' ID '%s'",
                user_info['email'], provider, user_info['id'])

        await self._on_login_successful(user, connection)
