#!/bin/bash
#
set -e -x

export TEUTHOLOGY_CONFIG=$PWD/.teuthology.yaml

SUITE=orch/cephadm/smb/
SUITE_ARGS=(--filter-out ubuntu,runc --filter smb)  # deploy_smb_proxy_{en,dis}abled
BUILD_BRANCH=wip-phlogistonjohn-testing-2025-07-23-1649
SUITE_BRANCH=wip-phlogistonjohn-testing-2025-07-23-1649
DB_FILE=$HOME/tmp/teuthology/queue.db
OVERRIDES=$PWD/overrides.yaml
BACKEND="sqlite://${DB_FILE}"
VENVDIR=_venv
MTYPE=oquack
VMS=(ceph0 ceph1 ceph2 ceph3)
SQM=teuthology.machines.sqlite_pool

my_overrides() {
    cat <<EOF
#overrides:
#  cephadm:
#    image: "quay.io/phlogistonjohn/ceph:dev"
#    cephadm_from_container: true
#  verify_ceph_hash: false
#verify_ceph_hash: false
EOF
}

tcmd() {
    teuth_command="$1"
    if ! command -v "$teuth_command" >/dev/null; then
        echo "no ${teuth_command} found (need to activiate a virtual env?)"
        echo "   hint, try to run: . ${VENVDIR}/bin/activate"
        exit 2
    fi
    "$@"
}

machines_add_ceph_vms() {
    python -m $SQM --rm-all
    cmd=(python -m $SQM --machine-type="${MTYPE}")
    for h in "${VMS[@]}" ; do
        case "$h" in
            ceph*) : ;;
            *) continue ;;
        esac
        cmd+=(--add "${h}")
    done
    "${cmd[@]}" --list
}

machines_vm_revert() {
    for h in "${VMS[@]}" ; do
        virsh snapshot-revert --domain $h --snapshotname installed &
    done
    wait
}

keyzap() {
    for x in {200..210}; do
        ssh-keygen -R 192.168.76.$x || true
    done
}

for arg in "$@"; do
    echo "##==> $arg"
    case "$arg" in
        --set=*)
            v="${arg/--set=/}"
            eval "$v"
            echo "$foo"
        ;;
        setup-virtual-env)
            test -d "${VENVDIR}" || ${TEUTH_PYTHON:-python3} -m venv "${VENVDIR}"
            "${VENVDIR}/bin/pip" install -r requirements.txt
            "${VENVDIR}/bin/pip" install --require-virtualenv -e .
        ;;
        remove-virtual-env)
            rm -rf "${VENVDIR}"
        ;;
        veryclean)
            rm -rf ~/tmp/teuthology
        ;;
        clean)
            rm -rf "${DB_FILE}"  ~/tmp/teuthology/log/* ~/tmp/teuthology/archive/*
        ;;
        liteclean)
            rm -rf ~/tmp/teuthology/archive/*
        ;;
        vm-revert)
            export LIBVIRT_DEFAULT_URI=qemu:///system
            machines_vm_revert
            machines_add_ceph_vms
        ;;
        vm-relearn)
            # tell teuthology the vms are available even if they are not
            mkdir -p ~/tmp/teuthology/log/
            mkdir -p ~/tmp/teuthology/archive/
            machines_add_ceph_vms
        ;;
        enqueue)
            mkdir -p ~/tmp/teuthology/log/
            mkdir -p ~/tmp/teuthology/archive/
            my_overrides > "${OVERRIDES}"
            tcmd teuthology-suite --arch=x86_64  --suite "${SUITE}" "${SUITE_ARGS[@]}"  -m "${MTYPE}" --ceph "${BUILD_BRANCH}" --suite-branch "${SUITE_BRANCH}" -b "${BACKEND}" "${OVERRIDES}" |& tee x
        ;;
        start)
            keyzap
            tcmd teuthology-dispatcher --log-dir $HOME/tmp/teuthology/log --tube "${MTYPE}" -v --exit-on-empty-queue
        ;;
        rerun)
            test "${JOB_YAML}"
            tcmd teuthology --interactive-on-error "${JOB_YAML}"
        ;;
        rerun-loop)
            if [ ! -f "${JOB_YAML}" ]; then
                echo "JOB_YAML not set or invalid"
                exit 1
            fi
            export JOB_YAML
            round=0
            echo > attempts.count
            while sleep 20; do
                round=$((round+1))
                echo "round ${round} starting" | tee -a attempts.count
                $0 vm-revert
                sleep 1
                $0 rerun || break
                echo "round ${round} done" | tee -a attempts.count
            done
        ;;
        cat-sample-config)
cat <<EOF
ssh_config_path: ~/devel/oquack/ssh-config
src_base_path: $HOME/tmp/teuthology
archive_base: $HOME/tmp/teuthology/archive
ceph_qa_suite_git_url: file://$HOME/devel/ceph/ceph
ceph_git_url: file://$HOME/devel/ceph/ceph
job_queue_backend: sqlite://$HOME/tmp/teuthology/queue.db

queue_host: localhost
queue_port: zzzzbest

teuthology_path: $HOME/devel/teuthology/wip
results_server: null
lock_server: null
lab_domain: cx.fdopen.net
machine_pool: sqlite://$HOME/tmp/teuthology/machines.db
reserve_machines: 0
test_user: ceph

defaults:
  cephadm:
    containers:
      image: quay.ceph.io/ceph-ci/ceph
vip:
  - machine_subnet: 192.168.76.0/24
    virtual_subnet: 192.168.176.0/22
suite_verify_ceph_hash: false
EOF
        ;;
    esac
done
