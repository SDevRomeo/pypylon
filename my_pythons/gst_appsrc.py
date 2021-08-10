#!/usr/bin/env python3
# redoing gsttest1.py since its the only one that works for now

from __future__ import print_function
import sys
sys.path.append('../')
import gi
import configparser
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
gi.require_version('GstBase', '1.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from ctypes import *
import time
import math
import platform

from pypylon import pylon
from pypylon import genicam
import sys, signal

from gi.repository import GObject, Gst, GstBase, Gtk, GstApp

roll = 0
ip = '10.10.0.10'  # read from file
recnum = "09"  # read from file

# computed variables
port0 = str(recnum)
port1 = str(int(port0) + 1)

x264enc_name = "x264enc"
vaapih264enc_name = "vaapih264enc"
# encoder_name = vaapih264enc_name
encoder_name = vaapih264enc_name

rec_jpegenc_name = "vaapijpegenc"
rec_h264enc_name = "vaapih264enc"
rec_encoder_name = rec_h264enc_name
rec_encoder_kbps = 10000
maxCamerasToUse = 2

def bus_call(bus, message, loop):
    t = message.type
    if t == Gst.MessageType.EOS:
        sys.stdout.write("End-of-stream\n")
        loop.quit()
    elif t==Gst.MessageType.WARNING:
        err, debug = message.parse_warning()
        sys.stderr.write("Warning: %s: %s\n" % (err, debug))
    elif t == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        sys.stderr.write("Error: %s: %s\n" % (err, debug))
        loop.quit()
    return True

def grab_one_frame(camera):
    grabResult = camera.RetrieveResult(100, pylon.TimeoutHandling_ThrowException)
    cameraContextValue = grabResult.GetCameraContext()
    print("Camera ", cameraContextValue, ": ", camera[cameraContextValue].GetDeviceInfo().GetModelName())

    # Now, the image data can be processed.
    print("GrabSucceeded: ", grabResult.GrabSucceeded())
    print("SizeX: ", grabResult.GetWidth())
    print("SizeY: ", grabResult.GetHeight())
    img = grabResult.GetArray()
    return img

def needdata_from_camera0_cb(self, src, length):
    buf = Gst.Buffer.new_allocate(self.size)
    # add framegrabber here
    buf.fill(0, self.data)
    src.emit('push-buffer', buf)

def needdata_from_camera1_cb(self, src, length):
    buf = Gst.Buffer.new_allocate(self.size)
    #add framegrabber here
    buf.fill(0, self.data)
    src.emit('push-buffer', buf)

def pipeline():
    GObject.threads_init()
    Gst.init(None)
    Gst.debug_set_active(True)
    Gst.debug_set_default_threshold(3)

    tlFactory = pylon.TlFactory.GetInstance()
    devices = tlFactory.EnumerateDevices()
    if len(devices) == 0:  # error check -NO CAMS PLUGGED IN-
        raise pylon.RuntimeException("No camera present.")

    cameras = pylon.InstantCameraArray(min(len(devices), maxCamerasToUse))
    num_of_camera_sources = cameras.GetSize()
    for i, cam in enumerate(cameras):
        cam.Attach(tlFactory.CreateDevice(devices[i]))
        print(i)
        # Print the model name of the camera.
        print("Using device ", cam.GetDeviceInfo().GetModelName())  # DON'T THINK I NEED THIS ONE IT'S JUST A CHECK
        cam.Open()
        cam.GainAuto.SetValue("Off")  # works when putting in auto values to off
        cam.Gain.SetValue(5)
        cam.ExposureAuto.SetValue('Off')
        cam.ExposureTime.SetValue(130)  # works make it into an argument when ready

        # Line 1 settings
        cam.LineSelector.SetValue('Line1')
        cam.LineMode.SetValue('Input')
        cam.LineInverter.SetValue(False)  # think by default its this, ***issues with this one
        # cam.LineSource.SetValue('UserOutput1') #defaults to this no need

        # Line 2 settings
        cam.LineSelector.SetValue('Line2')
        cam.LineMode.SetValue('Output')
        cam.LineInverter.SetValue(True)  # this is the way
        cam.LineSource.SetValue('ExposureActive')
        # cam.UserOutputSelector.SetValue('UserOutput1') #defaults to this too
        cam.TriggerMode.SetValue('On')
        cam.TriggerSelector.SetValue('FrameStart')
        cam.TriggerSource.SetValue('Line1')
        # have to rotate one of them

    print("Creating Pipeline \n ")
    pipeline = Gst.Pipeline()
    for i in range(num_of_camera_sources):
        name = "appsrc%u" % i
        source = Gst.ElementFactory.make("appsrc", name)
        if not source:
            sys.stderr.write(" Unable to create appsrc \n")
        pipeline.add(source)
        capfilter = Gst.ElementFactory.make("capfilter", name)
        rec_video_cap_string = "video/x-raw,format=GRAY8,framerate=60/1"
        name = "capfilter%u" % i
        capfilter = Gst.ElementFactory.make("capsfilter", name)
        if not capfilter:
            sys.stderr.write(" Unable to create videorate_capfilter \n")
        caps = Gst.Caps.from_string(rec_video_cap_string)
        capfilter.set_property("caps", caps)
        pipeline.add(capfilter)
        name = "tee%u" % i
        tee = Gst.ElementFactory.make("tee", name)
        if not tee:
            sys.stderr.write(" Unable to create tee \n")
        pipeline.add(tee)
        if i == 0:
            source.connect('need-data', needdata_from_camera0_cb)
        else:
            source.connect('need-data', needdata_from_camera1_cb)

        name = "timecodestamper%u" % i
        timecodestamper = Gst.ElementFactory.make("timecodestamper", name)
        if not timecodestamper:
            sys.stderr.write(" Unable to create timecodestamper \n")
        # try this
        zerotimecode = GstVideo.VideoTimeCode(60, 1, 0, 0, 0, 0, 0, 0, 0)
        timecodestamper.set_property('first-timecode', zerotimecode)

        pipeline.add(timecodestamper)
        name = "timeoverlay%u" % i
        timeoverlay = Gst.ElementFactory.make("timeoverlay", name)
        if not timeoverlay:
            sys.stderr.write(" Unable to create timeoverlay \n")
        timeoverlay.set_property('time-mode', 'time-code')
        timeoverlay.set_property('halignment', 'right')
        timeoverlay.set_property('valignment', 'bottom')
        pipeline.add(timeoverlay)
        name = "videoflip%u" % i
        videoflip = Gst.ElementFactory.make("videoflip", name)
        if not videoflip:
            sys.stderr.write(" Unable to create videoflip \n")
        videoflip.set_property('method', 'counterclockwise')
        pipeline.add(videoflip)
        name = "videoconvert%u" % i
        videoconvert = Gst.ElementFactory.make("videoconvert", name)
        if not videoconvert:
            sys.stderr.write(" Unable to create videoconvert \n")
        pipeline.add(videoconvert)
        name = "vaapipostproc%u" % i
        vaapipostproc = Gst.ElementFactory.make("vaapipostproc", name)
        if not vaapipostproc:
            sys.stderr.write(" Unable to create vaapipostproc \n")
        pipeline.add(vaapipostproc)
        name = "queue%u" % i
        queue = Gst.ElementFactory.make("queue", name)
        if not queue:
            sys.stderr.write(" Unable to create queue \n")
        pipeline.add(queue)
        name = rec_encoder_name + ("_rec%u" % i)
        rec_encoder = Gst.ElementFactory.make(rec_encoder_name, name)
        if not rec_encoder:
            sys.stderr.write(" Unable to create rec_encoder \n")
        use_hw_encoder = False
        if rec_encoder_name.startswith("vaapih264enc"):
            use_hw_encoder = True
            rec_encoder.set_property('bitrate', rec_encoder_kbps)
            rec_encoder.set_property('min-qp', 30)
            rec_encoder.set_property('quality-level', 7)
        else:
            rec_encoder.set_property('quality', 75)
        pipeline.add(rec_encoder)
        name = "h264parse_rec%u" % i
        h264parse = Gst.ElementFactory.make("h264parse", name)
        if not h264parse:
            sys.stderr.write(" Unable to create h264parse \n")
        pipeline.add(h264parse)
        name = "qtmux%u" % i
        qtmux = Gst.ElementFactory.make("qtmux", name)
        if not qtmux:
            sys.stderr.write(" Unable to create qtmux \n")
        pipeline.add(qtmux)
        name = "filesink%u" % i
        filesink = Gst.ElementFactory.make("filesink", name)
        if not filesink:
            sys.stderr.write(" Unable to create filesink \n")
        filepath = "/home/face/Pictures/SRTEST60_cam%u.mov" % i
        filesink.set_property('location', filepath)
        pipeline.add(filesink)
        
    loop = GObject.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print("Starting pipeline \n")
    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except:
        pass
    # cleanup
    pipeline.set_state(Gst.State.NULL)

if __name__ == '__main__':
    sys.exit(pipeline())
    print("abcd")