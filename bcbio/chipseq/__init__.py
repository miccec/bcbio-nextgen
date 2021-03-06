import os
import sys
import toolz as tz
from bcbio import utils
from bcbio import bam
from bcbio.pipeline import config_utils
import bcbio.pipeline.datadict as dd
from bcbio.ngsalign import bowtie2, bwa
from bcbio.distributed.transaction import file_transaction
from bcbio.provenance import do
from bcbio.log import logger

def clean_chipseq_alignment(data):
    aligner = dd.get_aligner(data)
    data["align_bam"] = dd.get_work_bam(data)
    if aligner:
        if aligner == "bowtie2":
            filterer = bowtie2.filter_multimappers
        elif aligner == "bwa":
            filterer = bwa.filter_multimappers
        else:
            logger.error("ChIP-seq only supported for bowtie2 and bwa.")
            sys.exit(-1)
        unique_bam = filterer(dd.get_work_bam(data), data)
        data["work_bam"] = unique_bam
    else:
        logger.info("Warning: When BAM file is given as input, bcbio skips multimappers removal."
                    "If BAM is not cleaned for peak calling, can result in downstream errors.")
    # lcr_bed = utils.get_in(data, ("genome_resources", "variation", "lcr"))
    encode_bed = tz.get_in(["genome_resources", "variation", "encode_blacklist"], data)
    if encode_bed:
        data["work_bam"] = _prepare_bam(data["work_bam"], encode_bed, data['config'])
        bam.index(data["work_bam"], data['config'])
    data["bigwig"] = _bam_coverage(dd.get_sample_name(data), dd.get_work_bam(data), data)
    return [[data]]

def _prepare_bam(bam_file, bed_file, config):
    """Remove regions from bed files"""
    if not bam_file or not bed_file:
        return bam_file
    out_file = utils.append_stem(bam_file, '_filter')
    bedtools = config_utils.get_program("bedtools", config)
    if not utils.file_exists(out_file):
        with file_transaction(out_file) as tx_out:
            cmd = "{bedtools} subtract -nonamecheck -A -a {bam_file} -b {bed_file} > {tx_out}"
            do.run(cmd.format(**locals()), "Clean %s" % bam_file)
    return out_file

def  get_genome(genome):
    from bcbio.chipseq import macs2
    loaded = macs2.HS
    if genome in loaded:
        return loaded[genome]

def _bam_coverage(name, bam_input, data):
    """Run bamCoverage from deeptools"""
    cmd = ("{bam_coverage} -b {bam_input} -o {bw_output} "
          "--binSize 20 --effectiveGenomeSize {size} "
          "--smoothLength 60 --extendReads 150 --centerReads -p {cores}")
    size = int(get_genome(dd.get_genome_build(data)))
    cores = dd.get_num_cores(data)
    try:
        bam_coverage = config_utils.get_program("bamCoverage", data)
    except config_utils.CmdNotFound:
        logger.info("No bamCoverage found, skipping bamCoverage.")
        return None
    bw_output = os.path.join(os.path.dirname(bam_input), "%s.bw" % name)
    if utils.file_exists(bw_output):
        return bw_output
    with file_transaction(bw_output) as out_tx:
        do.run(cmd.format(**locals()), "Run bamCoverage in %s" % name)
    return bw_output
