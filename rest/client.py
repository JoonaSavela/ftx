import time
import urllib.parse
from typing import Optional, Dict, Any, List

from requests import Request, Session, Response
import hmac
from ciso8601 import parse_datetime
import functools


def slow_down(func):
    @functools.wraps(func)
    def wrapper_slow_down(*args, **kwargs):
        t0 = time.perf_counter()
        value = func(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        if elapsed < 0.05:
            time.sleep(0.05 - elapsed)
        return value

    return wrapper_slow_down


class FtxClient:
    _ENDPOINT = "https://ftx.com/api/"

    def __init__(self, api_key=None, api_secret=None, subaccount_name=None) -> None:
        self._session = Session()
        self._api_key = api_key
        self._api_secret = api_secret
        self._subaccount_name = subaccount_name

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("POST", path, json=params)

    def _delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("DELETE", path, json=params)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        request = Request(method, self._ENDPOINT + path, **kwargs)
        self._sign_request(request)
        response = self._session.send(request.prepare())
        return self._process_response(response)

    def _sign_request(self, request: Request) -> None:
        ts = int(time.time() * 1000)
        prepared = request.prepare()
        signature_payload = f"{ts}{prepared.method}{prepared.path_url}".encode()
        if prepared.body:
            signature_payload += prepared.body
        signature = hmac.new(
            self._api_secret.encode(), signature_payload, "sha256"
        ).hexdigest()
        request.headers["FTX-KEY"] = self._api_key
        request.headers["FTX-SIGN"] = signature
        request.headers["FTX-TS"] = str(ts)
        if self._subaccount_name:
            request.headers["FTX-SUBACCOUNT"] = urllib.parse.quote(
                self._subaccount_name
            )

    def _process_response(self, response: Response) -> Any:
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        else:
            if not data["success"]:
                raise Exception(data["error"])
            return data["result"]

    @slow_down
    def list_futures(self) -> List[dict]:
        return self._get("futures")

    @slow_down
    def list_markets(self) -> List[dict]:
        return self._get("markets")

    @slow_down
    def get_orderbook(self, market: str, depth: int = None) -> dict:
        return self._get(f"markets/{market}/orderbook", {"depth": depth})

    @slow_down
    def get_trades(self, market: str) -> dict:
        return self._get(f"markets/{market}/trades")

    @slow_down
    def get_account_info(self) -> dict:
        return self._get(f"account")

    @slow_down
    def get_open_orders(self, market: str = None) -> List[dict]:
        return self._get(f"orders", {"market": market})

    @slow_down
    def get_order_history(
        self,
        market: str = None,
        side: str = None,
        order_type: str = None,
        start_time: float = None,
        end_time: float = None,
    ) -> List[dict]:
        return self._get(
            f"orders/history",
            {
                "market": market,
                "side": side,
                "orderType": order_type,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    @slow_down
    def get_conditional_order_history(
        self,
        market: str = None,
        side: str = None,
        type: str = None,
        order_type: str = None,
        start_time: float = None,
        end_time: float = None,
    ) -> List[dict]:
        return self._get(
            f"conditional_orders/history",
            {
                "market": market,
                "side": side,
                "type": type,
                "orderType": order_type,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    @slow_down
    def transfer_to_subaccount(
        self,
        coin: str,
        size: float,
        source: Optional[str] = None,
        destination: Optional[str] = None,
    ) -> Dict:
        return self._post(
            f"subaccounts/transfer",
            {"coin": coin, "size": size, "source": source, "destination": destination},
        )

    @slow_down
    def get_historical_prices(
        self,
        market: str,
        resolution: float,
        limit: Optional[float] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[dict]:
        path = f"markets/{market}/candles"
        return self._get(
            path,
            {
                "resolution": resolution,
                "limit": limit,
                "start_time": start_time,
                "end_time": end_time,
            },
        )

    @slow_down
    def modify_order(
        self,
        existing_order_id: Optional[str] = None,
        existing_client_order_id: Optional[str] = None,
        price: Optional[float] = None,
        size: Optional[float] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        assert (existing_order_id is None) ^ (
            existing_client_order_id is None
        ), "Must supply exactly one ID for the order to modify"
        assert (price is None) or (size is None), "Must modify price or size of order"
        path = (
            f"orders/{existing_order_id}/modify"
            if existing_order_id is not None
            else f"orders/by_client_id/{existing_client_order_id}/modify"
        )
        return self._post(
            path,
            {
                **({"size": size} if size is not None else {}),
                **({"price": price} if price is not None else {}),
                **(
                    {"clientId": client_order_id} if client_order_id is not None else {}
                ),
            },
        )

    # Only works for market orders
    @slow_down
    def modify_conditional_order(
        self,
        order_id: str,
        order_type: Optional[str] = None,
        triggerPrice: Optional[float] = None,
        trailValue: Optional[float] = None,
        size: Optional[float] = None,
    ) -> dict:
        assert order_type in ("stop", "takeProfit", "trailingStop")
        if order_type == "trailingStop":
            assert (trailValue is not None) or (
                size is not None
            ), "trailingStop must modify trailValue or size of order"
        else:
            assert (triggerPrice is not None) or (
                size is not None
            ), "Other than trailingStop must modify triggerPrice or size of order"

        path = f"conditional_orders/{order_id}/modify"
        return self._post(
            path,
            {
                **({"size": size} if size is not None else {}),
                **({"triggerPrice": triggerPrice} if triggerPrice is not None else {}),
                **({"trailValue": trailValue} if trailValue is not None else {}),
            },
        )

    @slow_down
    def get_conditional_orders(self, market: str = None) -> List[dict]:
        return self._get(f"conditional_orders", {"market": market})

    @slow_down
    def place_order(
        self,
        market: str,
        side: str,
        price: float,
        size: float,
        type: str = "limit",
        reduce_only: bool = False,
        ioc: bool = False,
        post_only: bool = False,
        client_id: str = None,
    ) -> dict:
        return self._post(
            "orders",
            {
                "market": market,
                "side": side,
                "price": price,
                "size": size,
                "type": type,
                "reduceOnly": reduce_only,
                "ioc": ioc,
                "postOnly": post_only,
                "clientId": client_id,
            },
        )

    @slow_down
    def place_conditional_order(
        self,
        market: str,
        side: str,
        size: float,
        order_type: str = "stop",
        limit_price: float = None,
        reduce_only: bool = False,
        cancel: bool = True,
        triggerPrice: float = None,
        trailValue: float = None,
    ) -> dict:
        """
        To send a Stop Market order, set order_type='stop' and supply a triggerPrice
        To send a Stop Limit order, also supply a limit_price
        To send a Take Profit Market order, set order_type='takeProfit' and supply a triggerPrice
        To send a Trailing Stop order, set order_type='trailingStop' and supply a trailValue
        """
        assert order_type in ("stop", "takeProfit", "trailingStop")
        assert (
            order_type not in ("stop", "takeProfit") or triggerPrice is not None
        ), "Need trigger prices for stop losses and take profits"
        assert order_type not in ("trailingStop",) or (
            triggerPrice is None and trailValue is not None
        ), "Trailing stops need a trail value and cannot take a trigger price"

        if order_type == "trailingStop":
            return self._post(
                "conditional_orders",
                {
                    "market": market,
                    "side": side,
                    "trailValue": trailValue,
                    "size": size,
                    "reduceOnly": reduce_only,
                    "type": order_type,
                    "cancelLimitOnTrigger": cancel,
                },
            )
        else:
            return self._post(
                "conditional_orders",
                {
                    "market": market,
                    "side": side,
                    "triggerPrice": triggerPrice,
                    "size": size,
                    "reduceOnly": reduce_only,
                    "type": order_type,
                    "cancelLimitOnTrigger": cancel,
                    "orderPrice": limit_price,
                },
            )

    @slow_down
    def cancel_order(self, order_id: str) -> dict:
        return self._delete(f"orders/{order_id}")

    @slow_down
    def cancel_conditional_order(self, order_id: str) -> dict:
        return self._delete(f"conditional_orders/{order_id}")

    @slow_down
    def cancel_orders(
        self,
        market_name: str = None,
        conditional_orders: bool = False,
        limit_orders: bool = False,
    ) -> dict:
        return self._delete(
            f"orders",
            {
                "market": market_name,
                "conditionalOrdersOnly": conditional_orders,
                "limitOrdersOnly": limit_orders,
            },
        )

    @slow_down
    def get_fills(self) -> List[dict]:
        return self._get(f"fills")

    @slow_down
    def get_balances(self) -> List[dict]:
        return self._get("wallet/balances")

    @slow_down
    def get_deposit_address(self, ticker: str) -> dict:
        return self._get(f"wallet/deposit_address/{ticker}")

    @slow_down
    def get_positions(self, show_avg_price: bool = False) -> List[dict]:
        return self._get("positions", {"showAvgPrice": show_avg_price})

    @slow_down
    def get_position(self, name: str, show_avg_price: bool = False) -> dict:
        return next(
            filter(lambda x: x["future"] == name, self.get_positions(show_avg_price)),
            None,
        )

    @slow_down
    def get_all_trades(
        self, market: str, start_time: float = None, end_time: float = None
    ) -> List:
        ids = set()
        limit = 100
        results = []
        while True:
            response = self._get(
                f"markets/{market}/trades",
                {
                    "end_time": end_time,
                    "start_time": start_time,
                },
            )
            deduped_trades = [r for r in response if r["id"] not in ids]
            results.extend(deduped_trades)
            ids |= {r["id"] for r in deduped_trades}
            print(f"Adding {len(response)} trades with end time {end_time}")
            if len(response) == 0:
                break
            end_time = min(parse_datetime(t["time"]) for t in response).timestamp()
            if len(response) < limit:
                break
        return results
