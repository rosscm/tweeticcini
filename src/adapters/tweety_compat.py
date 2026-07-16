import inspect
from urllib.parse import urlparse

from src.log import setup_logger


log = setup_logger(__name__)
_bootstrap_warning_logged = False


def apply_tweety_compat_patch() -> None:
    try:
        from tweety.exceptions import TwitterError
        from tweety.http import Request
        from tweety.types.n_types import GenericError
    except Exception:
        return

    if getattr(Request, '_tweeticcini_compat_patched', False):
        return

    async def patched_init_local_api(self):
        global _bootstrap_warning_logged
        cookies = await self.remove_cookies()
        if not self._transaction:
            try:
                home_page_html = await self.get_home_html()
                from tweety.transaction import TransactionGenerator

                self._transaction = TransactionGenerator(home_page_html)
            except Exception as exc:
                # X's homepage markup changes often; keep going without a transaction id
                # rather than failing auth/bootstrap completely.
                if not _bootstrap_warning_logged:
                    log.warning(f'continuing without Tweety transaction bootstrap: {type(exc).__name__}: {exc}')
                    _bootstrap_warning_logged = True
                self._transaction = None

        if not self._guest_token:
            self._guest_token = await self._get_guest_token()

        self.cookies = cookies

    async def patched_get_response(self, return_raw=False, ignore_none_data=False, is_document=False, **request_data):
        if not self._transaction or not self._guest_token:
            await self._init_local_api()

        new_request = request_data
        new_request["headers"] = self._get_request_headers(request_data.get("headers", {}))
        new_request["cookies"] = self._cookie

        if self._transaction:
            try:
                transaction_id = self._transaction.generate_transaction_id(
                    new_request["method"],
                    urlparse(new_request["url"]).path,
                )
                new_request["headers"]["x-client-transaction-id"] = transaction_id
            except Exception as exc:
                log.warning(f'failed to generate Tweety transaction id; retrying without it: {type(exc).__name__}: {exc}')

        response = None
        last_error = None

        for _retry in range(self._retries):
            try:
                response = await self._session.request(**new_request)
                break
            except Exception as request_failed:
                last_error = request_failed

        if not response:
            raise last_error

        await self._update_rate_limit(response, inspect.stack()[1][3])
        await self._update_cookies(response)

        if is_document:
            return response

        response_json = response.json()
        if ignore_none_data and len(response.text) == 0:
            return None

        if (not response_json and response.text and response.text.lower() == "rate limit exceeded") or response.status_code == 429:
            response_json = {"errors": [{"code": 88, "message": "Rate limit exceeded."}]}
        elif not response_json and response.status_code in [403, 401]:
            response_json = {"errors": [{"code": 32, "message": "Couldn't authenticate you"}]}

        if not response_json:
            raise TwitterError(
                error_code=response.status_code,
                error_name="Server Error",
                response=response,
                message="Unknown Error Occurs on Twitter"
            )

        if response_json.get("errors") and not response_json.get('data'):
            error = response_json['errors'][0]
            error_code = error.get("code", 0)
            error_message = error.get("message")
            return GenericError(response, error_code, error_message)

        if return_raw:
            return response

        return response_json

    Request._init_local_api = patched_init_local_api
    Request.__get_response__ = patched_get_response
    Request._tweeticcini_compat_patched = True
