seed = 1
seqfile = tiny.txt
Imapfile = tiny.imap
jobname = out
speciesdelimitation = 0
speciestree = 0
species&tree = 3  A  B  C
                  2  2  2
                  ((A,B),C);
usedata = 1
nloci = 2
cleandata = 0
thetaprior = invgamma 3 0.01
tauprior = invgamma 3 0.02
finetune = 1
burnin = 10
sampfreq = 1
nsample = 20
