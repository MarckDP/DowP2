def playlist_format_selector(mode, quality):
    if mode == "audio_only":
        if quality == "best_compatible":
            return "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio[ext=mp3]/bestaudio[ext=wav]/bestaudio/best"
        return "bestaudio/best"

    if quality == "best_compatible":
        return (
            "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']+bestaudio[acodec~='^(aac|mp4a|pcm_s16le|pcm_s24le|mp3|ac3)']/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext~='^(mp4|mov|avi)'][vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/best"
        )
    if quality == "best":
        return "bestvideo+bestaudio/best"
    if str(quality).isdigit():
        h = str(quality)
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    return "bestvideo+bestaudio/best"


def quick_format_selector(mode, quality):
    if mode == "audio_only":
        if quality == "best_compatible":
            return playlist_format_selector(mode, "best_compatible")
        return "bestaudio/best"

    if mode == "video_only":
        if quality == "best_compatible":
            return "bestvideo[vcodec~='^(avc1|h264|hevc|h265|prores|dnxhd|dnxhr|cfhd)']/bestvideo[ext=mp4]/bestvideo/best"
        if quality == "best":
            return "bestvideo/best"
        if str(quality).isdigit():
            return f"bestvideo[height<={quality}]/best[height<={quality}]/best"
        return "bestvideo/best"

    return playlist_format_selector("video+audio", quality)
