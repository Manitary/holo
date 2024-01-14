from typing import Any, TypedDict
from time import struct_time

# TODO: mark required/not required attributes?

# Youtube JSON response structure


class YoutubeContentDetails(TypedDict):
    videoId: str
    videoPublishedAt: str


class YoutubeSnippet(TypedDict):
    publishedAt: str
    channelId: str
    title: str
    description: str
    thumbnails: dict[str, dict[str, Any]]
    channelTitle: str
    tags: list[str]
    categoryId: str
    liveBroadcastContent: str
    localized: dict[str, str]
    defaultAudioLanguage: str


class YoutubeVideoStatus(TypedDict):
    uploadStatus: str
    privacyStatus: str
    license: str
    embeddable: bool
    publicStatsViewable: bool
    madeForKids: bool


class YoutubeItem(TypedDict):
    kind: str
    etag: str


class YoutubeVideoItem(YoutubeItem):
    id: str
    snippet: YoutubeSnippet
    status: YoutubeVideoStatus


class YoutubePlaylistItem(YoutubeItem):
    id: str
    contentDetails: YoutubeContentDetails


class YoutubePayload(YoutubeItem):
    pageInfo: dict[str, int]


class YoutubePlaylistPayload(YoutubePayload):
    items: list[YoutubePlaylistItem]


class YoutubeVideoPayload(YoutubePayload):
    items: list[YoutubeVideoItem]


# Crunchyroll RSS feed response structure


class CrunchyrollTag(TypedDict):
    term: str
    scheme: str
    label: str | None


class CrunchyrollDetails(TypedDict):
    type: str
    language: str | None
    base: str
    value: str


class CrunchyrollMediaRestriction(TypedDict):
    relationship: str
    type: str
    content: list[str]


class CrunchyrollLink(TypedDict):
    rel: str
    type: str
    href: str


class CrunchyrollThumbnail(TypedDict):
    url: str
    width: str
    height: str


class CrunchyrollImage(TypedDict):
    href: str
    links: list[CrunchyrollLink]
    link: str
    title: str
    title_detail: CrunchyrollDetails


class CrunchyrollFeed(TypedDict):
    title: str
    title_detail: CrunchyrollDetails
    links: list[dict[str, str]]
    link: str
    subtitle: str
    subtitle_detail: CrunchyrollDetails
    image: CrunchyrollImage
    ttl: str
    rating: str
    language: str
    rights: str
    rights_detail: CrunchyrollDetails
    crunchyroll_simulcast: str


class CrunchyrollEntry(TypedDict):
    title: str
    title_detail: CrunchyrollDetails
    links: list[CrunchyrollLink]
    link: str
    id: str
    guidislink: bool
    summary: str
    summary_detail: CrunchyrollDetails
    tags: list[CrunchyrollTag]
    crunchyroll_mediaid: str
    published: str
    published_parsed: struct_time
    crunchyroll_freepubdate: str
    crunchyroll_premiumpubdate: str
    crunchyroll_endpubdate: str
    crunchyroll_premiumendpubdate: str
    crunchyroll_freeendpubdate: str
    crunchyroll_seriestitle: str
    crunchyroll_episodetitle: str
    crunchyroll_episodenumber: str
    crunchyroll_duration: str
    crunchyroll_publisher: str
    crunchyroll_subtitlelanguages: str
    crunchyroll_isclip: bool
    media_content: list[dict[str, str]]
    media_restriction: CrunchyrollMediaRestriction
    restriction: str
    media_credit: list[dict[str, str]]
    credit: str
    media_rating: dict[str, str]
    rating: str
    media_thumbnail: list[CrunchyrollThumbnail]
    href: str
    media_keywords: str
    crunchyroll_modifieddate: str


class CrunchyrollPayload(TypedDict):
    bozo: bool
    entries: list[CrunchyrollEntry]
    feed: CrunchyrollFeed
    headers: dict[str, Any]
    encoding: str
    version: str
    namespaces: dict[str, str]
