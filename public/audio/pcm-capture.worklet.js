class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.chunkFrames = options.processorOptions?.chunkFrames ?? 1600;
    this.buffer = new Float32Array(this.chunkFrames);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    const channel = input?.[0];

    if (!channel || channel.length === 0) {
      return true;
    }

    let sourceOffset = 0;

    while (sourceOffset < channel.length) {
      const writable = Math.min(this.chunkFrames - this.offset, channel.length - sourceOffset);
      this.buffer.set(channel.subarray(sourceOffset, sourceOffset + writable), this.offset);
      this.offset += writable;
      sourceOffset += writable;

      if (this.offset === this.chunkFrames) {
        this.port.postMessage(this.buffer.slice(0));
        this.offset = 0;
      }
    }

    return true;
  }
}

registerProcessor("pcm-capture-processor", PcmCaptureProcessor);
