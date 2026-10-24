/** SDK 연동 경계에서 실제로 사용하는 지도·오버레이·이벤트 계약. */
export interface KakaoLatLng {
  getLat(): number;
  getLng(): number;
}

export interface KakaoPixel {
  x: number;
  y: number;
}
export interface KakaoBounds {
  extend(point: KakaoLatLng): void;
}
export interface KakaoOverlay {
  setMap(map: KakaoMapInstance | null): void;
}
export interface KakaoCluster {
  getClusterMarker(): { setZIndex(value: number): void; getContent?(): HTMLElement | string } | null;
}
export interface KakaoClusterer {
  clear(): void;
  addMarkers(markers: KakaoOverlay[]): void;
}

export interface KakaoMapInstance {
  addControl(control: object, position: unknown): void;
  removeControl?(control: object): void;
  setBounds(
    bounds: KakaoBounds,
    top: number,
    right: number,
    bottom: number,
    left: number,
  ): void;
  setCenter(point: KakaoLatLng): void;
  panTo(point: KakaoLatLng): void;
  getCenter(): KakaoLatLng;
  getLevel(): number;
  setLevel(level: number): void;
  panBy(x: number, y: number): void;
  getProjection(): { containerPointFromCoords(point: KakaoLatLng): KakaoPixel };
}

export interface KakaoMouseEvent {
  latLng?: KakaoLatLng;
}
export interface KakaoEventArgs {
  click: [event: KakaoMouseEvent];
  clustered: [clusters: KakaoCluster[]];
  clusterclick: [];
  dragstart: [];
  center_changed: [];
  zoom_start: [];
  zoom_changed: [];
  idle: [];
  resize: [];
}

interface SearchRow {
  x: string;
  y: string;
  place_name?: string;
  address_name?: string;
  road_address_name?: string;
}
type SearchCallback = (rows: SearchRow[], status: string) => void;
type Options = Record<string, unknown>;

export interface KakaoSDK {
  maps: {
    load(callback: () => void): void;
    Map: new (element: HTMLElement, options: Options) => KakaoMapInstance;
    LatLng: new (latitude: number, longitude: number) => KakaoLatLng;
    LatLngBounds: new () => KakaoBounds;
    ZoomControl: new () => object;
    ControlPosition: { RIGHT: unknown };
    Size: new (width: number, height: number) => object;
    Point: new (x: number, y: number) => object;
    MarkerImage: new (url: string, size: object, options: Options) => object;
    Marker: new (options: Options) => KakaoOverlay;
    Polygon: new (options: Options) => KakaoOverlay;
    CustomOverlay: new (options: Options) => KakaoOverlay;
    Circle: new (options: Options) => KakaoOverlay;
    Polyline: new (options: Options) => KakaoOverlay;
    MarkerClusterer: new (options: Options) => KakaoClusterer;
    event: {
      addListener<E extends keyof KakaoEventArgs>(
        target: object,
        name: E,
        handler: (...args: KakaoEventArgs[E]) => void,
      ): void;
      removeListener<E extends keyof KakaoEventArgs>(
        target: object,
        name: E,
        handler: (...args: KakaoEventArgs[E]) => void,
      ): void;
      trigger<E extends keyof KakaoEventArgs>(target: object, name: E): void;
    };
    services?: {
      Status: { OK: string; ZERO_RESULT: string };
      Places: new () => {
        keywordSearch(
          query: string,
          callback: SearchCallback,
          options: Options,
        ): void;
      };
      Geocoder: new () => {
        addressSearch(
          query: string,
          callback: SearchCallback,
          options: Options,
        ): void;
      };
    };
  };
}
