"""고정 localhost 검수 API만 호출한다. 운영 URL/Worker/발송을 호출하지 않는다."""
from __future__ import annotations

import concurrent.futures
import http.client
import json
from pathlib import Path
import threading
import time

OUT = Path(__import__("os").environ.get("NEARBY_INTEGRATION_OUT", "/workspace/nearby-integration-checks"))
OUT.mkdir(parents=True, exist_ok=True)
samples, stop = [], threading.Event()


def request(method, path, data=None, timeout=50):
    connection = http.client.HTTPConnection("127.0.0.1", 8877, timeout=timeout)
    started = time.monotonic()
    try:
        connection.request(method, path, body=json.dumps(data).encode() if data is not None else None,
                           headers={"Content-Type":"application/json"} if data is not None else {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read(), round((time.monotonic()-started)*1000)
    finally:
        connection.close()


def state():
    status, _, body, _ = request("GET", "/__qa/status")
    assert status == 200
    return json.loads(body)


def wait_active(active):
    limit = time.monotonic() + 10
    while time.monotonic() < limit:
        value = state()
        if value["activeCaptures"] == active: return
        time.sleep(.05)
    raise AssertionError(f"Active captures did not become {active}")


def observe():
    while not stop.is_set():
        try:
            status, _, _, milliseconds = request("GET", "/api/v1/health", timeout=5)
            current = state()
            samples.append({"healthStatus":status,"healthMs":milliseconds,"memoryBytes":current["cgroupMemoryBytes"]})
        except Exception as error:
            samples.append({"error":type(error).__name__})
        stop.wait(.05)


def pdf(case, latitude=35.8714, longitude=128.6014, radius=5, expected="captured"):
    result = request("POST", "/api/v1/reports/nearby.pdf", {"latitude":latitude,"longitude":longitude,
        "label":"보고서 연결 검수 기준점","address":"개발용 API 연결 검수","radius_km":radius})
    status, headers, body, milliseconds = result
    header = {k.lower():v for k,v in headers.items()}
    assert status == 200, (case,status)
    assert header.get("x-nearby-map-status") == expected, (case,header.get("x-nearby-map-status"),state())
    assert body.startswith(b"%PDF")
    (OUT / f"{case}.pdf").write_bytes(body)
    record = {"case":case,"status":status,"mapStatus":expected,"facilityCount":header["x-nearby-facility-count"],
              "facilityDigest":header["x-nearby-facility-digest"],"milliseconds":milliseconds,"bytes":len(body)}
    print(json.dumps(record,ensure_ascii=False),flush=True)
    return record


def main():
    records = []
    watcher = threading.Thread(target=observe,daemon=True);watcher.start()
    try:
        records.append(pdf("three"))
        records.append(pdf("zero",radius=.1))
        records.append(pdf("single",latitude=36.3526,longitude=128.697,radius=5))
        records.append(pdf("many",radius=50))
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(pdf,"concurrent-map")
            wait_active(1)
            records.append(pdf("concurrent-busy",expected="busy"))
            records.append(first.result())
        connection = http.client.HTTPConnection("127.0.0.1",8877,timeout=50)
        connection.request("POST","/api/v1/reports/nearby.pdf",body=json.dumps({"latitude":35.8714,"longitude":128.6014,"label":"취소 검수","radius_km":5}),headers={"Content-Type":"application/json"})
        wait_active(1);connection.close();wait_active(0)
        records.append({"case":"disconnect","browserReleased":True})
        records.append(pdf("after-cancel"))
        request("POST","/__qa/mode",{"mode":"blocked"})
        records.append(pdf("map-timeout",expected="timeout"))
        request("POST","/__qa/mode",{"mode":"unavailable"})
        records.append(pdf("map-unavailable",expected="unavailable"))
        request("POST","/__qa/mode",{"mode":"capture"})
        assert state()["maxActiveCaptures"] == 1
    finally:
        stop.set();watcher.join(timeout=10)
        final=state()
        (OUT/"api-checks.json").write_text(json.dumps({"scope":"Local API container, real SDK and tiles via proxy; QA static asset response overrides. Blocked tile test is an intentional failure injection.","records":records,"samples":samples,"server":final},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
