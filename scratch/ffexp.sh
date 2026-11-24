set -x
ffmpeg -version | head -1
ffmpeg -y -loglevel error -f lavfi -i testsrc2=size=320x240:rate=30:duration=16 -f lavfi -i sine=frequency=440:sample_rate=44100:duration=16 -c:v libx264 -preset ultrafast -c:a aac -shortest in.mp4
S="between(t,0,3)+between(t,5,9)"
d(){ ffprobe -v error -show_entries stream=codec_type,duration -of compact "$1"; }
ffmpeg -y -loglevel error -i in.mp4 -filter_complex "[0:a]aselect='$S',asetpts=N/SR/TB[a]" -map "[a]" -c:a aac a1.m4a; d a1.m4a
ffmpeg -y -loglevel error -i in.mp4 -filter_complex "[0:a]aselect='$S'[a]" -map "[a]" -c:a pcm_s16le a2.wav; d a2.wav
ffmpeg -y -loglevel error -i in.mp4 -filter_complex "[0:a]aselect='$S',asetpts=N/SR/TB[a]" -map "[a]" -c:a pcm_s16le a3.wav; d a3.wav
ffmpeg -y -loglevel error -i in.mp4 -filter_complex "[0:a]aselect='between(pts*TB,0,3)+between(pts*TB,5,9)',asetpts=N/SR/TB[a]" -map "[a]" -c:a pcm_s16le a4.wav; d a4.wav
ffmpeg -y -loglevel error -i in.mp4 -filter_complex "[0:a]aselect='$S',asetpts=N/SR/TB,anull[a]" -map "[a]" -c:a aac a5.m4a; d a5.m4a
ffmpeg -y -loglevel error -i in.mp4 -af "aselect='$S',asetpts=N/SR/TB" -vn -c:a pcm_s16le a6.wav; d a6.wav
ffmpeg -y -loglevel debug -i in.mp4 -filter_complex "[0:a]aselect='$S',asetpts=N/SR/TB[a]" -map "[a]" -c:a pcm_s16le a7.wav 2>&1 | grep -iE "select|aselect" | head -20
